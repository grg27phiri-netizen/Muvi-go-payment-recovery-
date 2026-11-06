import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash
from app import app, init_db


class PaymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.db")
        self.old_path = app.config.get("DATABASE_PATH")
        app.config["DATABASE_PATH"] = self.db_path
        app.config["TESTING"] = True
        init_db()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO users(name, email, password_hash)
               VALUES(?, ?, ?)""",
            (
                "Sandbox User",
                "sandbox@example.test",
                generate_password_hash("TestPassword123!"),
            ),
        )
        conn.commit()
        conn.close()
        self.client = app.test_client()
        login = self.client.post(
            "/api/auth/login",
            json={
                "email": "sandbox@example.test",
                "password": "TestPassword123!",
            },
        )
        assert login.status_code == 200, login.json

    def tearDown(self):
        if self.old_path is not None:
            app.config["DATABASE_PATH"] = self.old_path
        self.temp_dir.cleanup()

    def counts(self):
        conn = sqlite3.connect(self.db_path)
        payments = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
        subscriptions = conn.execute(
            "SELECT COUNT(*) FROM subscriptions"
        ).fetchone()[0]
        conn.close()
        return payments, subscriptions

    def test_plan_catalogue(self):
        r = self.client.get("/api/payment/plans")
        self.assertEqual(r.status_code, 200)
        plans = {p["id"]: p["amount"] for p in r.json["plans"]}
        self.assertEqual(plans, {"weekly": 10, "monthly": 30, "annual": 300})

    def test_readiness_does_not_claim_live_provider(self):
        r = self.client.get("/api/payments/readiness")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json["live_provider_connected"])

    def test_valid_payment_remains_pending_without_subscription(self):
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 1, "plan": "weekly", "provider": "mtn_momo"
        })
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json["status"], "pending")
        self.assertEqual(self.counts(), (1, 0))

    def test_invalid_plan_rejected(self):
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 1, "plan": "lifetime", "provider": "mtn_momo"
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_provider_rejected(self):
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 1, "plan": "weekly", "provider": "unknown"
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_user_id_types_rejected(self):
        for user_id in ["1", 1.0, True, 0, -1, None, [], {}]:
            with self.subTest(user_id=repr(user_id)):
                r = self.client.post("/api/payments/initiate", json={
                    "user_id": user_id,
                    "plan": "weekly",
                    "provider": "mtn_momo",
                })
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json["error"], "invalid_user")
                self.assertEqual(self.counts(), (0, 0))

    def test_non_object_json_rejected(self):
        for payload in [[], ["weekly"], "invalid", 12]:
            with self.subTest(payload=repr(payload)):
                r = self.client.post("/api/payments/initiate", json=payload)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json["error"], "invalid_request")
                self.assertEqual(self.counts(), (0, 0))

    def test_non_string_plan_and_provider_rejected(self):
        invalid_cases = [
            ([], "mtn_momo", "invalid_plan"),
            ({}, "mtn_momo", "invalid_plan"),
            ("weekly", [], "invalid_provider"),
            ("weekly", {}, "invalid_provider"),
        ]
        for plan, provider, expected_error in invalid_cases:
            with self.subTest(plan=repr(plan), provider=repr(provider)):
                r = self.client.post("/api/payments/initiate", json={
                    "user_id": 1,
                    "plan": plan,
                    "provider": provider,
                })
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json["error"], expected_error)
                self.assertEqual(self.counts(), (0, 0))

    def test_unknown_user_rejected(self):
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 99999, "plan": "weekly", "provider": "airtel_money"
        })
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json["error"], "user_mismatch")
        self.assertEqual(self.counts(), (0, 0))

    def test_payment_initiation_requires_login(self):
        self.client.post("/api/auth/logout")
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 1, "plan": "weekly", "provider": "mtn_momo"
        })
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.counts(), (0, 0))

    def test_customer_cannot_initiate_for_another_user(self):
        r = self.client.post("/api/payments/initiate", json={
            "user_id": 2, "plan": "weekly", "provider": "mtn_momo"
        })
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json["error"], "user_mismatch")
        self.assertEqual(self.counts(), (0, 0))


if __name__ == "__main__":
    unittest.main()
