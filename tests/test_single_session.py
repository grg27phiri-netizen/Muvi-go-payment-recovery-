import tempfile
import unittest
import time
from pathlib import Path

import app as application


class SingleSessionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        test_db = Path(self.tmp.name) / "session_test.db"

        application.app.config.update(
            DATABASE_PATH=str(test_db),
            TESTING=True,
            SECRET_KEY="test-only-secret-key"
        )

        application.init_db()
        self.first = application.app.test_client()
        self.second = application.app.test_client()

        response = self.first.post(
            "/api/auth/register",
            json={
                "name": "Test Viewer",
                "email": "viewer@example.com",
                "password": "StrongPass123"
            }
        )
        self.assertEqual(response.status_code, 201)

    def tearDown(self):
        self.tmp.cleanup()

    def login_second(self):
        return self.second.post(
            "/api/auth/login",
            json={
                "email": "viewer@example.com",
                "password": "StrongPass123"
            }
        )

    def test_second_device_rejected(self):
        response = self.login_second()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json["error"],
            "account currently in use"
        )

    def test_first_session_remains_authenticated(self):
        self.login_second()
        self.assertTrue(
            self.first.get("/api/auth/me").json["authenticated"]
        )

    def test_logout_releases_lock(self):
        self.first.post("/api/auth/logout")
        response = self.login_second()
        self.assertEqual(response.status_code, 200)

    def test_expired_session_releases_lock(self):
        conn = application.db()
        try:
            conn.execute(
                "UPDATE auth_sessions SET expires_at = ?",
                (time.time() - 1,)
            )
            conn.commit()
        finally:
            conn.close()

        self.assertFalse(
            self.first.get("/api/auth/me").json["authenticated"]
        )

        response = self.login_second()
        self.assertEqual(response.status_code, 200)

    def test_old_session_invalid_after_new_login(self):
        self.first.post("/api/auth/logout")
        self.login_second()

        self.assertFalse(
            self.first.get("/api/auth/me").json["authenticated"]
        )
        self.assertTrue(
            self.second.get("/api/auth/me").json["authenticated"]
        )


if __name__ == "__main__":
    unittest.main()
