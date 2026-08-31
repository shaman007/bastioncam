import sqlite3
import tempfile
import unittest
from pathlib import Path

from bastioncam.db import connect
from bastioncam.webauth import (
    check_credentials,
    create_session,
    create_user,
    delete_session,
    session_user,
)


class WebAuthTest(unittest.TestCase):
    def test_password_and_session_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            user = create_user(db, "admin", "correct horse battery staple")
            self.assertIsNone(check_credentials(db, "admin", "wrong password"))
            self.assertEqual(check_credentials(db, "admin", "correct horse battery staple")["id"], user["id"])
            token, csrf = create_session(db, user["id"])
            active = session_user(db, token)
            self.assertEqual(active["username"], "admin")
            self.assertEqual(active["csrf_token"], csrf)
            delete_session(db, token)
            self.assertIsNone(session_user(db, token))
            db.close()

    def test_password_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            with self.assertRaises(ValueError):
                create_user(db, "admin", "short")
            with self.assertRaises(ValueError):
                create_user(db, "not valid", "correct horse battery staple")
            db.close()

    def test_reader_role_and_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "test.db")
            reader = create_user(db, "reader", "correct horse battery staple", "reader")
            credentials = check_credentials(db, "reader", "correct horse battery staple")
            self.assertEqual(credentials["role"], "reader")
            token, _ = create_session(db, reader["id"])
            self.assertEqual(session_user(db, token)["role"], "reader")
            db.execute("UPDATE users SET blocked_at='2026-08-31T12:00:00+00:00' WHERE id=?", (reader["id"],))
            db.commit()
            self.assertIsNone(check_credentials(db, "reader", "correct horse battery staple"))
            self.assertIsNone(session_user(db, token))
            db.close()

    def test_existing_users_migrate_to_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("INSERT INTO users(username,password_hash,created_at) VALUES('legacy','hash','2026-01-01')")
            db.commit();db.close()
            db = connect(path)
            self.assertEqual(db.execute("SELECT role FROM users WHERE username='legacy'").fetchone()[0], "admin")
            db.close()


if __name__ == "__main__":
    unittest.main()
