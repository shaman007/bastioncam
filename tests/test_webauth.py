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


if __name__ == "__main__":
    unittest.main()
