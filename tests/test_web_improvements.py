import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlparse, parse_qs

from bastioncam.db import connect
from bastioncam.web import App
from bastioncam.webauth import create_session, create_user


class CaptureApp(App):
    def send_page(self, body, status=200):
        self.body, self.status = body, status

    def send_json(self, value, status=200):
        self.value, self.status = value, status

    def current_user(self):
        return {'id': 1, 'role': 'admin', 'csrf_token': 'csrf'}


class ImprovementsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.db'
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.app = object.__new__(CaptureApp)
        self.app.db_path = str(self.path)
        self.app.path = '/'

    def seed_recordings(self):
        for number in range(2):
            cid = f'collector-{number}'
            self.db.execute('INSERT INTO collectors(id,name,created_at) VALUES(?,?,?)', (cid, cid, '2026-08-31'))
            pane = self.db.execute('INSERT INTO panes(collector_id,session_name,pane_key,first_seen,last_seen) VALUES(?,?,?,?,?)',
                                   (cid, cid, cid, '2026-08-31', '2026-08-31')).lastrowid
            snap = self.db.execute('INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(?,?,?,?)',
                                   (pane, '2026-08-31T12:00:00+00:00', f'needle {cid}', cid)).lastrowid
            self.db.execute("""INSERT INTO segments(pane_id,first_snapshot_id,last_snapshot_id,started_at,ended_at,
                source_text,summary,status,created_at) VALUES(?,?,?,?,?,?,?,'done',?)""",
                (pane, snap, snap, '2026-08-31T12:00:00+00:00', '2026-08-31T12:01:00+00:00',
                 cid, f'Summary {cid}', '2026-08-31'))
        self.db.execute("""INSERT INTO period_summaries(period_type,period_start,period_end,summary,source_hash,
            segment_count,updated_at) VALUES('day','2026-08-31T00:00:00+00:00','2026-09-01T00:00:00+00:00',
            'Global summary of both collectors','hash',2,'2026-08-31')""")
        self.db.commit()

    def test_calendar_and_sidebar_scope_and_navigation(self):
        self.seed_recordings()
        self.app.path = '/calendar?collector=collector-1&month=2026-08&day=2026-08-31'
        self.app.calendar_view('2026-08', '2026-08-31', 'collector-1')
        self.assertIn('1 snapshots', self.app.body)
        self.assertNotIn('2 snapshots', self.app.body)
        self.assertIn('Summary collector-1', self.app.body)
        self.assertNotIn('Summary collector-0', self.app.body)
        self.assertNotIn('Global summary', self.app.body)
        self.assertIn('collector=collector-1', self.app.body)
        self.assertIn("value='collector-1' selected", self.app.body)
        sidebar = self.app.sidebar()
        self.assertIn('Summary collector-1', sidebar)
        self.assertNotIn('Summary collector-0', sidebar)
        self.app.calendar_view('2026-08', '2026-08-31')
        self.assertIn('Global summary', self.app.body)

    def test_scoped_calendar_without_episodes_never_uses_global_summary(self):
        self.seed_recordings()
        self.app.calendar_view('2026-08', '2026-08-31', 'unknown')
        self.assertNotIn('Global summary', self.app.body)
        self.assertIn('No recorded activity', self.app.body)

    def test_search_pagination_preserves_filters_and_bounds_page(self):
        self.seed_recordings()
        pane = self.db.execute('SELECT id FROM panes LIMIT 1').fetchone()[0]
        for i in range(45):
            self.db.execute('INSERT INTO snapshots(pane_id,captured_at,content,content_hash) VALUES(?,?,?,?)',
                            (pane, f'2026-08-31T13:00:{i:02d}+00:00', f'needle item {i}', str(i)))
        self.db.commit()
        self.app.path = '/?q=needle&collector=collector-0&page=2'
        with patch('bastioncam.web.parse_query', return_value=('needle', None, None, None)):
            self.app.index('needle', collector_id='collector-0')
        self.assertEqual(self.app.body.count('class=result '), 20)
        self.assertIn('Page 2', self.app.body)
        self.assertIn('q=needle&amp;collector=collector-0&amp;page=3', self.app.body)
        self.app.path = '/?page=garbage'
        self.assertEqual(self.app.pagination(45)[0], 0)
        self.app.path = '/?page=99999999'
        self.assertEqual(self.app.pagination(45)[0], 40)

    def test_collector_command_uses_configured_public_url(self):
        from bastioncam.oidc import Config
        import os
        config = Config('https://idp.example', 'cam', 'test', 'https://callback.example/auth/oidc/callback')
        with patch.object(self.app, 'oidc_config', return_value=config), patch.dict(os.environ, {'BASTIONCAM_PUBLIC_URL': 'https://public.example/'}):
            self.assertIn('--server-url https://public.example', self.app.collector_command())
            self.assertIn('; Secure', self.app.session_cookie('synthetic'))

    def test_inventory_page_is_bounded_and_token_copy_is_one_time(self):
        for i in range(25):
            self.db.execute('INSERT INTO collectors(id,name,created_at) VALUES(?,?,?)',
                            (str(i), f'collector {i}', f'2026-08-{i+1:02d}'))
        self.db.commit()
        self.app.path = '/admin/collectors'
        self.app.admin_collectors(token='synthetic-test-token', created_name='test')
        self.assertEqual(self.app.body.count('class=collector-row'), 20)
        self.assertIn('data-copy=new-token', self.app.body)
        self.assertIn('data-copy=collector-command', self.app.body)
        self.assertIn('synthetic-test-token', self.app.body)
        self.assertIn('read -r -s BASTIONCAM_TOKEN', self.app.body)
        self.app.path += '?page=2'
        self.app.admin_collectors()
        self.assertEqual(self.app.body.count('class=collector-row'), 5)
        self.assertNotIn('synthetic-test-token', self.app.body)

    def test_health_checks_schema_read_write_and_rolls_back(self):
        self.app.health()
        self.assertEqual(self.app.status, 200)
        self.assertIsNone(self.db.execute("SELECT 1 FROM server_settings WHERE key='health_probe'").fetchone())
        self.db.execute('PRAGMA user_version=999')
        self.app.health()
        self.assertEqual(self.app.status, 503)
        self.assertEqual(self.app.value, {'status': 'unavailable'})
        self.app.db_path = str(self.path.parent / 'missing.db')
        self.app.health()
        self.assertEqual(self.app.status, 503)
        self.assertFalse(Path(self.app.db_path).exists())


class HTTPUsersTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'test.db'
        db = connect(self.path)
        self.admin = create_user(db, 'admin', 'test password long enough')
        self.reader = create_user(db, 'reader', 'test password long enough', 'reader')
        self.admin_token, self.csrf = create_session(db, self.admin['id'])
        self.reader_token, self.reader_csrf = create_session(db, self.reader['id'])
        db.close()
        handler = type('TestHandler', (App,), {'db_path': str(self.path), 'log_message': lambda *args: None})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.directory.cleanup()

    def request(self, method, path, token='', form=None):
        connection = HTTPConnection(*self.server.server_address, timeout=10)
        connection.request(method, path, body=urlencode(form) if form is not None else None,
                           headers={'Cookie': f'zh_session={token}', 'Content-Type': 'application/x-www-form-urlencoded'})
        response = connection.getresponse()
        status, headers, body = response.status, response.getheaders(), response.read().decode()
        connection.close()
        return status, headers, body

    def test_reader_denied_admin_and_csrf_required(self):
        self.assertEqual(self.request('GET', '/admin/users', self.reader_token)[0], 403)
        self.assertEqual(self.request('GET', '/admin/collectors', self.reader_token)[0], 403)
        self.assertEqual(self.request('POST', '/admin/users/action', self.reader_token,
                                      dict(csrf=self.reader_csrf, user_id=self.admin['id'], action='delete'))[0], 403)
        self.assertEqual(self.request('POST', '/admin/users/action', self.admin_token,
                                      dict(csrf='wrong', user_id=self.reader['id'], action='delete'))[0], 403)

    def test_role_changes_revoke_sessions_and_self_change_rejected(self):
        self.assertEqual(self.request('POST', '/admin/users/action', self.admin_token,
                                      dict(csrf=self.csrf, user_id=self.reader['id'], action='role', role='admin'))[0], 303)
        self.assertEqual(self.request('GET', '/admin/users', self.reader_token)[0], 303)
        db = connect(self.path)
        self.assertEqual(db.execute('SELECT role FROM users WHERE id=?', (self.reader['id'],)).fetchone()[0], 'admin')
        db.close()
        for action in ('role', 'block', 'delete'):
            self.assertEqual(self.request('POST', '/admin/users/action', self.admin_token,
                                          dict(csrf=self.csrf, user_id=self.admin['id'], action=action, role='reader'))[0], 400)

    def test_oidc_http_login_cookie_callback_and_blocking(self):
        import time
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from bastioncam.oidc import Config
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid='http-key', alg='RS256')
        config = Config('https://idp.example', 'cam', 'test', 'https://cam.example/auth/oidc/callback')
        metadata = dict(issuer=config.issuer, authorization_endpoint='https://idp.example/auth',
                        token_endpoint='https://idp.example/token', jwks_uri='https://idp.example/keys')
        nonce = ''

        def provider(url, data=None):
            if url.endswith('openid-configuration'): return metadata
            if url.endswith('/keys'): return {'keys': [jwk]}
            self.assertEqual(parse_qs(data.decode())['redirect_uri'], [config.redirect_uri])
            claims = dict(iss=config.issuer, sub='http-user', aud='cam', nonce=nonce,
                          exp=int(time.time())+60, iat=int(time.time()), preferred_username='SSOuser')
            return {'id_token': jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'http-key'})}

        def callback(state):
            connection = HTTPConnection(*self.server.server_address, timeout=10)
            connection.request('GET', '/auth/oidc/callback?' + urlencode(dict(state=state, code='synthetic-code')),
                               headers={'Cookie': 'zh_oidc=' + state})
            response = connection.getresponse()
            result = response.status, response.getheaders(), response.read().decode()
            connection.close()
            return result

        with patch('bastioncam.web.App.oidc_config', return_value=config), patch('bastioncam.oidc.request_json', side_effect=provider):
            self.assertIn('Sign in with SSO', self.request('GET', '/login')[2])
            status, headers, _ = self.request('GET', '/auth/oidc/login')
            self.assertEqual(status, 303)
            params = parse_qs(urlparse(dict(headers)['Location']).query)
            state, nonce = params['state'][0], params['nonce'][0]
            self.assertIn('HttpOnly; Secure; SameSite=Lax', dict(headers)['Set-Cookie'])
            status, headers, _ = callback(state)
            self.assertEqual(status, 303)
            cookies = [value for name, value in headers if name == 'Set-Cookie']
            self.assertEqual(len(cookies), 2)
            token = cookies[0].split(';')[0].split('=', 1)[1]
            self.assertIn('Secure', cookies[0])
            self.assertIn('Max-Age=0', cookies[1])
            self.assertEqual(self.request('GET', '/', token)[0], 200)
            self.assertEqual(self.request('GET', '/admin/users', token)[0], 403)
            self.assertEqual(callback(state)[0], 401)
            db = connect(self.path)
            user_id = db.execute('SELECT user_id FROM oidc_identities').fetchone()[0]
            db.close()
            self.assertEqual(self.request('POST', '/admin/users/action', self.admin_token,
                                          dict(csrf=self.csrf, user_id=user_id, action='block'))[0], 303)
            self.assertEqual(self.request('GET', '/', token)[0], 303)
            _, headers, _ = self.request('GET', '/auth/oidc/login')
            params = parse_qs(urlparse(dict(headers)['Location']).query)
            state, nonce = params['state'][0], params['nonce'][0]
            self.assertEqual(callback(state)[0], 401)

    def test_health_is_public_and_login_sso_is_optional(self):
        self.assertEqual(self.request('GET', '/healthz')[0], 200)
        with patch('bastioncam.web.App.oidc_config', return_value=None):
            status, headers, body = self.request('GET', '/login')
            self.assertEqual(status, 200)
            self.assertNotIn('Sign in with SSO', body)
            self.assertIn(('Cache-Control', 'no-store'), headers)


if __name__ == '__main__':
    unittest.main()
