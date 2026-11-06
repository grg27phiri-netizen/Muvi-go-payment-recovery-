import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash
from app import app, init_db
from payments import apply_verified_payment


class PaymentConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "confirmation.db")
        self.old_path = app.config.get("DATABASE_PATH")
        self.old_testing = app.config.get("TESTING", False)

        app.config["DATABASE_PATH"] = self.db_path
        app.config["TESTING"] = True
        self.app_context = app.app_context()
        self.app_context.push()
        init_db()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO users(name, email, password_hash)
               VALUES (?, ?, ?)""",
            (
                "Test User",
                "confirmation@example.test",
                generate_password_hash("TestPassword123!"),
            ),
        )
        conn.commit()
        conn.close()

        self.client = app.test_client()
        login = self.client.post(
            "/api/auth/login",
            json={
                "email": "confirmation@example.test",
                "password": "TestPassword123!",
            },
        )
        assert login.status_code == 200, login.json

    def tearDown(self):
        self.app_context.pop()
        app.config["DATABASE_PATH"] = self.old_path
        app.config["TESTING"] = self.old_testing
        self.temp.cleanup()

    def start_payment(self, provider="mtn_momo", plan="weekly"):
        response = self.client.post(
            "/api/payments/initiate",
            json={"user_id": 1, "plan": plan, "provider": provider},
        )
        self.assertEqual(response.status_code, 202)
        return response.json["payment_ref"]

    def counts(self):
        conn = sqlite3.connect(self.db_path)
        payment_rows = conn.execute(
            "SELECT status, provider_transaction_id FROM payments"
        ).fetchall()
        subscription_count = conn.execute(
            "SELECT COUNT(*) FROM subscriptions"
        ).fetchone()[0]
        conn.close()
        return payment_rows, subscription_count

    def test_verified_confirmation_activates_once(self):
        ref = self.start_payment()
        result, status = apply_verified_payment(
            ref, "TEST-TXN-001", 10, "ZMW", "mtn_momo"
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "successful")
        rows, subscriptions = self.counts()
        self.assertEqual(rows[0][0], "successful")
        self.assertEqual(subscriptions, 1)

    def test_repeated_confirmation_does_not_duplicate_subscription(self):
        ref = self.start_payment()
        apply_verified_payment(
            ref, "TEST-TXN-002", 10, "ZMW", "mtn_momo"
        )
        result, status = apply_verified_payment(
            ref, "TEST-TXN-002", 10, "ZMW", "mtn_momo"
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(self.counts()[1], 1)

    def test_wrong_amount_does_not_activate(self):
        ref = self.start_payment()
        result, status = apply_verified_payment(
            ref, "TEST-TXN-003", 1, "ZMW", "mtn_momo"
        )

        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "amount_mismatch")
        rows, subscriptions = self.counts()
        self.assertEqual(rows[0][0], "pending")
        self.assertEqual(subscriptions, 0)

    def test_wrong_provider_does_not_activate(self):
        ref = self.start_payment(provider="mtn_momo")
        result, status = apply_verified_payment(
            ref, "TEST-TXN-004", 10, "ZMW", "airtel_money"
        )

        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "provider_mismatch")
        self.assertEqual(self.counts()[1], 0)

    def test_wrong_currency_does_not_activate(self):
        ref = self.start_payment()
        result, status = apply_verified_payment(
            ref, "TEST-TXN-005", 10, "USD", "mtn_momo"
        )

        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "currency_mismatch")
        self.assertEqual(self.counts()[1], 0)

    def test_one_provider_transaction_cannot_be_reused(self):
        first = self.start_payment()
        second = self.start_payment()

        result1, status1 = apply_verified_payment(
            first, "TEST-TXN-006", 10, "ZMW", "mtn_momo"
        )
        result2, status2 = apply_verified_payment(
            second, "TEST-TXN-006", 10, "ZMW", "mtn_momo"
        )

        self.assertEqual(status1, 200)
        self.assertEqual(status2, 409)
        self.assertEqual(result2["error"], "transaction_already_used")
        self.assertEqual(self.counts()[1], 1)

    def test_zero_row_payment_update_does_not_activate_subscription(self):
        ref = self.start_payment()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """CREATE TRIGGER ignore_payment_update
               BEFORE UPDATE ON payments
               WHEN OLD.payment_ref = NEW.payment_ref
               BEGIN
                   SELECT RAISE(IGNORE);
               END"""
        )
        conn.commit()
        conn.close()

        result, status = apply_verified_payment(
            ref, "TEST-TXN-ZERO-ROW", 10, "ZMW", "mtn_momo"
        )

        self.assertEqual(status, 409)
        self.assertEqual(result["error"], "payment_update_failed")
        rows, subscriptions = self.counts()
        self.assertEqual(rows[0][0], "pending")
        self.assertIsNone(rows[0][1])
        self.assertEqual(subscriptions, 0)

    def test_invalid_amount_values_are_rejected(self):
        invalid_values = [1.5, True, False, "10", 0, -10, None, "abc"]

        for index, amount in enumerate(invalid_values):
            with self.subTest(amount=repr(amount)):
                ref = self.start_payment()
                result, status = apply_verified_payment(
                    ref,
                    f"INVALID-AMOUNT-{index}",
                    amount,
                    "ZMW",
                    "mtn_momo",
                )

                self.assertEqual(status, 400)
                self.assertEqual(result["error"], "invalid_amount")

                conn = sqlite3.connect(self.db_path)
                payment_status = conn.execute(
                    "SELECT status FROM payments WHERE payment_ref = ?",
                    (ref,),
                ).fetchone()[0]
                conn.close()

                self.assertEqual(payment_status, "pending")
                self.assertEqual(self.counts()[1], 0)

    def test_subscription_insert_failure_rolls_back_payment(self):
        ref = self.start_payment()

        # Simulate a database failure during subscription creation.
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TRIGGER fail_subscription_insert
            BEFORE INSERT ON subscriptions
            BEGIN
                SELECT RAISE(ABORT, 'simulated subscription failure');
            END
        """)
        conn.commit()
        conn.close()

        result, status = apply_verified_payment(
            ref, "TEST-TXN-ROLLBACK", 10, "ZMW", "mtn_momo"
        )

        self.assertEqual(status, 500)
        self.assertEqual(
            result["error"], "confirmation_integrity_error"
        )

        rows, subscriptions = self.counts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "pending")
        self.assertIsNone(rows[0][1])
        self.assertEqual(subscriptions, 0)

    def test_no_public_confirmation_route_exists(self):
        routes = {
            rule.rule for rule in app.url_map.iter_rules()
        }
        self.assertNotIn("/api/payments/confirm", routes)
        self.assertNotIn("/api/payments/webhook", routes)


if __name__ == "__main__":
    unittest.main()
