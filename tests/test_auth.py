import tempfile
import unittest
from pathlib import Path

import app as application


class MuviGoAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        test_db = Path(self.tmp.name) / "auth_test.db"
        application.app.config.update(
            DATABASE_PATH=str(test_db),
            TESTING=True,
            SECRET_KEY="test-only-secret-key",
        )
        application.init_db()
        self.client = application.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def register(self, email="viewer@example.com", password="StrongPass123"):
        return self.client.post("/api/auth/register", json={
            "name": "Test Viewer",
            "email": email,
            "password": password,
        })

    def test_register_creates_account_and_session(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["ok"])
        self.assertNotIn("password_hash", response.json["user"])
        self.assertTrue(self.client.get("/api/auth/me").json["authenticated"])

    def test_password_is_hashed_in_database(self):
        self.register()
        conn = application.db()
        try:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("viewer@example.com",),
            ).fetchone()
            self.assertIsNotNone(row["password_hash"])
            self.assertNotEqual(row["password_hash"], "StrongPass123")
        finally:
            conn.close()

    def test_duplicate_email_rejected_case_insensitively(self):
        self.register()
        response = self.register(email="VIEWER@example.com")
        self.assertEqual(response.status_code, 409)

    def test_short_password_rejected(self):
        response = self.register(password="short")
        self.assertEqual(response.status_code, 400)

    def test_invalid_login_rejected(self):
        self.register()
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={
            "email": "viewer@example.com",
            "password": "WrongPassword123",
        })
        self.assertEqual(response.status_code, 401)

    def test_login_and_logout(self):
        self.register()
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={
            "email": "VIEWER@example.com",
            "password": "StrongPass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/api/auth/me").json["authenticated"])
        self.client.post("/api/auth/logout")
        self.assertFalse(self.client.get("/api/auth/me").json["authenticated"])

    def test_invalid_registration_input_rejected(self):
        response = self.client.post("/api/auth/register", json={
            "name": "", "email": "not-an-email", "password": "StrongPass123",
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
