import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from bastioncam import oidc
from bastioncam.db import connect
from bastioncam.webauth import check_credentials, create_user


class OIDCTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid='test-key', alg='RS256', use='sig')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = connect(Path(self.directory.name) / 'test.db')
        self.addCleanup(self.db.close)
        self.config = oidc.Config('https://idp.example/realms/test', 'bastioncam', 'test-secret',
                                  'https://cam.example/auth/oidc/callback')
        self.metadata = dict(issuer=self.config.issuer, authorization_endpoint='https://idp.example/authorize',
                             token_endpoint='https://idp.example/token', jwks_uri='https://idp.example/keys')
        self.claim_changes = {}
        self.captured_exchange = {}
        self.mock = patch('bastioncam.oidc.request_json', side_effect=self.provider)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def provider(self, url, data=None):
        if url.endswith('/.well-known/openid-configuration'):
            return self.metadata
        if url == self.metadata['jwks_uri']:
            return {'keys': [self.jwk]}
        if url == self.metadata['token_endpoint']:
            self.captured_exchange = parse_qs(data.decode())
            claims = dict(iss=self.config.issuer, sub='subject-1', aud=self.config.client_id,
                          iat=int(time.time()), exp=int(time.time()) + 60, nonce=self.nonce,
                          preferred_username='alice')
            claims.update(self.claim_changes)
            return {'id_token': jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'test-key'})}
        raise AssertionError('Unexpected provider URL')

    def begin(self):
        url, state = oidc.begin(self.db, self.config)
        params = parse_qs(urlparse(url).query)
        self.nonce = params['nonce'][0]
        return state, params

    def complete(self, state):
        return oidc.complete(self.db, self.config, state, state, 'code')

    def test_code_flow_pkce_and_stable_identity_without_local_linking(self):
        local = create_user(self.db, 'alice', 'a long test password')
        state, params = self.begin()
        self.assertEqual(params['scope'], ['openid profile email'])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        user = self.complete(state)
        self.assertEqual(user['role'], 'reader')
        self.assertNotEqual(user['id'], local['id'])
        verifier = self.captured_exchange['code_verifier'][0]
        import base64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(challenge, params['code_challenge'][0])
        self.assertIsNone(check_credentials(self.db, user['username'], ''))
        state, _ = self.begin()
        self.assertEqual(self.complete(state)['id'], user['id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM oidc_flows').fetchone()[0], 0)

    def test_state_is_browser_bound_expiring_and_single_use(self):
        state, _ = self.begin()
        for browser_state in ('', 'another-browser'):
            with self.assertRaises(ValueError):
                oidc.complete(self.db, self.config, state, browser_state, 'code')
        self.complete(state)
        with self.assertRaises(ValueError):
            self.complete(state)
        state, _ = self.begin()
        self.db.execute('UPDATE oidc_flows SET expires_at=0'); self.db.commit()
        with self.assertRaises(ValueError):
            self.complete(state)

    def test_invalid_token_claims_are_rejected_and_flow_is_consumed(self):
        cases = [dict(nonce='wrong'), dict(iss='https://attacker.example'), dict(aud='another-client'),
                 dict(exp=1), dict(iat=int(time.time()) + 1000), dict(sub=''), dict(azp='another-client'),
                 dict(aud=['bastioncam', 'other']), dict(nonce=None)]
        for changes in cases:
            with self.subTest(changes=changes):
                self.claim_changes = changes
                state, _ = self.begin()
                with self.assertRaises((ValueError, jwt.PyJWTError)):
                    self.complete(state)
                self.assertEqual(self.db.execute('SELECT count(*) FROM oidc_identities').fetchone()[0], 0)
                with self.assertRaises(ValueError):
                    self.complete(state)

    def test_signature_algorithm_and_missing_claims_rejected(self):
        for encoded in (
            jwt.encode(dict(sub='fake'), 'attacker-key', algorithm='HS256', headers={'kid': 'test-key'}),
            jwt.encode(dict(iss=self.config.issuer, sub='fake'), self.key, algorithm='RS256', headers={'kid': 'test-key'}),
        ):
            state, _ = self.begin()
            provider = self.provider
            with patch('bastioncam.oidc.request_json', side_effect=lambda url, data=None:
                       {'id_token': encoded} if data else provider(url, data)):
                with self.assertRaises(jwt.PyJWTError):
                    self.complete(state)

    def test_blocked_user_cannot_login_and_same_subject_at_other_issuer_is_distinct(self):
        state, _ = self.begin(); user = self.complete(state)
        self.db.execute("UPDATE users SET blocked_at='blocked' WHERE id=?", (user['id'],)); self.db.commit()
        state, _ = self.begin()
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.complete(state)
        other = oidc.identity_user(self.db, 'https://other.example', 'subject-1')
        self.assertNotEqual(user['id'], other['id'])

    def test_discovery_issuer_and_insecure_endpoints_rejected(self):
        for changes in ({'issuer': 'https://other.example'}, {'token_endpoint': 'http://insecure.example/token'}):
            with self.subTest(changes=changes):
                with patch.dict(self.metadata, changes):
                    with self.assertRaises(ValueError):
                        self.begin()

    def test_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(oidc.Config.from_env())
            os.environ['BASTIONCAM_OIDC_ISSUER'] = 'https://idp.example'
            with self.assertRaises(ValueError):
                oidc.Config.from_env()
            for name, value in dict(CLIENT_ID='test', CLIENT_SECRET='test', REDIRECT_URI='http://cam.example/callback').items():
                os.environ['BASTIONCAM_OIDC_' + name] = value
            with self.assertRaises(ValueError):
                oidc.Config.from_env()


if __name__ == '__main__':
    unittest.main()
