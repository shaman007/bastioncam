"""OIDC authorization-code login with PKCE and single-use browser-bound state."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

import jwt


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('OIDC URLs must use HTTPS')
    return value


def request_json(url: str, data: bytes | None = None) -> dict:
    request = Request(https_url(url), data=data, headers={'Accept': 'application/json'})
    if data is not None:
        request.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('OIDC response too large')
        result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError('Invalid OIDC response')
    return result


@dataclass(frozen=True)
class Config:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> Config | None:
        names = ('ISSUER', 'CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI')
        values = [os.environ.get('BASTIONCAM_OIDC_' + name, '') for name in names]
        if not any(values):
            return None
        if not all(values):
            raise ValueError('Incomplete OIDC configuration')
        https_url(values[0]); https_url(values[3])
        if urlparse(values[0]).query or urlparse(values[3]).query:
            raise ValueError('OIDC issuer and callback must not contain a query')
        return cls(*values)

    def metadata(self) -> dict:
        metadata = request_json(self.issuer.rstrip('/') + '/.well-known/openid-configuration')
        if metadata.get('issuer') != self.issuer:
            raise ValueError('OIDC issuer mismatch')
        for name in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
            https_url(metadata[name])
        return metadata


def begin(db, config: Config) -> tuple[str, str]:
    metadata = config.metadata()
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    now = int(time.time())
    db.execute('DELETE FROM oidc_flows WHERE expires_at<=?', (now,))
    db.execute('INSERT INTO oidc_flows VALUES(?,?,?,?)',
               (hashlib.sha256(state.encode()).hexdigest(), nonce, verifier, now + 600))
    db.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params = urlencode(dict(response_type='code', client_id=config.client_id,
                           redirect_uri=config.redirect_uri, scope='openid profile email',
                           state=state, nonce=nonce, code_challenge=challenge, code_challenge_method='S256'))
    separator = '&' if '?' in metadata['authorization_endpoint'] else '?'
    return metadata['authorization_endpoint'] + separator + params, state


def complete(db, config: Config, state: str, browser_state: str, code: str) -> dict:
    if not state or not browser_state or not hmac.compare_digest(state, browser_state) or not code:
        raise ValueError('Invalid OIDC state')
    # DELETE RETURNING consumes the flow atomically, including on failed exchanges.
    flow = db.execute('DELETE FROM oidc_flows WHERE state_hash=? RETURNING *',
                      (hashlib.sha256(state.encode()).hexdigest(),)).fetchone()
    db.commit()
    if not flow or flow['expires_at'] <= time.time():
        raise ValueError('OIDC login expired or already used')
    metadata = config.metadata()
    token = request_json(metadata['token_endpoint'], urlencode(dict(
        grant_type='authorization_code', code=code, redirect_uri=config.redirect_uri,
        client_id=config.client_id, client_secret=config.client_secret,
        code_verifier=flow['verifier'])).encode())
    encoded = token['id_token']
    keys = request_json(metadata['jwks_uri'])
    # Never accept symmetric algorithms or keys supplied by the ID token.
    header = jwt.get_unverified_header(encoded)
    candidates = [key for key in keys.get('keys', []) if key.get('kid') == header.get('kid')
                  and key.get('use', 'sig') == 'sig' and key.get('kty') == 'RSA'
                  and key.get('alg', 'RS256') == 'RS256']
    if len(candidates) != 1:
        raise ValueError('Unknown OIDC signing key')
    key = jwt.PyJWK.from_dict(candidates[0], algorithm='RS256')
    claims = jwt.decode(encoded, key.key, algorithms=['RS256'], issuer=config.issuer,
                        audience=config.client_id, options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'nonce']})
    if not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], flow['nonce']):
        raise ValueError('OIDC nonce mismatch')
    if (('azp' in claims and claims['azp'] != config.client_id)
            or (isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != config.client_id)):
        raise ValueError('OIDC authorized party mismatch')
    if not isinstance(claims['sub'], str) or not claims['sub']:
        raise ValueError('Invalid OIDC subject')
    return identity_user(db, config.issuer, claims['sub'], claims.get('preferred_username', ''))


def identity_user(db, issuer: str, subject: str, display_name: str = '') -> dict:
    # No email/username linking: only the verified (issuer, subject) identifies a user.
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT u.* FROM oidc_identities i JOIN users u ON u.id=i.user_id '
                         'WHERE i.issuer=? AND i.subject=?', (issuer, subject)).fetchone()
        if row is None:
            label = ''.join(c for c in str(display_name) if c.isalnum() or c in '-_.')[:40] or 'oidc'
            username = label + '-' + secrets.token_hex(8)
            cursor = db.execute("INSERT INTO users(username,password_hash,created_at,role) VALUES(?,?,?,'reader')",
                                (username, '', datetime.now(timezone.utc).isoformat(timespec='seconds')))
            db.execute('INSERT INTO oidc_identities VALUES(?,?,?)', (issuer, subject, cursor.lastrowid))
            row = db.execute('SELECT * FROM users WHERE id=?', (cursor.lastrowid,)).fetchone()
        if row['blocked_at']:
            raise ValueError('Account blocked')
    return {key: row[key] for key in ('id', 'username', 'role')}
