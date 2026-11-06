import sqlite3
import uuid
from flask import Blueprint, current_app, jsonify, request
from auth import current_user

payments_bp = Blueprint("payments", __name__)

PLANS = {
    "weekly": {"amount": 10, "days": 7},
    "monthly": {"amount": 30, "days": 30},
    "annual": {"amount": 300, "days": 365},
}
PROVIDERS = {"mtn_momo", "airtel_money"}


def connect_db():
    conn = sqlite3.connect(current_app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def apply_verified_payment(
    payment_ref, provider_transaction_id, amount, currency, provider
):
    """
    Internal service for a future trusted provider adapter.

    Call ONLY after the adapter has independently authenticated the
    provider response and verified its transaction details. This function
    is not itself proof that a provider payment occurred.
    """
    if provider not in PROVIDERS:
        return {"ok": False, "error": "invalid_provider"}, 400

    if not isinstance(provider_transaction_id, str) or not provider_transaction_id.strip():
        return {"ok": False, "error": "invalid_transaction_id"}, 400

    if currency != "ZMW":
        return {"ok": False, "error": "currency_mismatch"}, 400

    # Plans use whole ZMW amounts. Do not coerce floats, strings, or booleans.
    if type(amount) is not int or amount <= 0:
        return {"ok": False, "error": "invalid_amount"}, 400

    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        payment = conn.execute(
            "SELECT * FROM payments WHERE payment_ref = ?",
            (payment_ref,),
        ).fetchone()

        if payment is None:
            conn.rollback()
            return {"ok": False, "error": "payment_not_found"}, 404

        if payment["provider"] != provider:
            conn.rollback()
            return {"ok": False, "error": "provider_mismatch"}, 400

        if payment["amount"] != amount:
            conn.rollback()
            return {"ok": False, "error": "amount_mismatch"}, 400

        if payment["status"] == "successful":
            if payment["provider_transaction_id"] == provider_transaction_id:
                conn.rollback()
                return {"ok": True, "status": "already_processed"}, 200
            conn.rollback()
            return {"ok": False, "error": "payment_already_confirmed"}, 409

        if payment["status"] != "pending":
            conn.rollback()
            return {"ok": False, "error": "payment_not_pending"}, 409

        duplicate = conn.execute(
            """SELECT payment_ref FROM payments
               WHERE provider = ? AND provider_transaction_id = ?""",
            (provider, provider_transaction_id),
        ).fetchone()

        if duplicate is not None:
            conn.rollback()
            return {"ok": False, "error": "transaction_already_used"}, 409

        cursor = conn.execute(
            """UPDATE payments
               SET status = 'successful',
                   provider_transaction_id = ?,
                   verified_at = CURRENT_TIMESTAMP
               WHERE payment_ref = ? AND status = 'pending'""",
            (provider_transaction_id, payment_ref),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return {"ok": False, "error": "payment_update_failed"}, 409

        plan_days = PLANS[payment["plan"]]["days"]

        active_expiry = conn.execute(
            """SELECT MAX(expires_at) AS expiry
               FROM subscriptions
               WHERE user_id = ?
                 AND status = 'active'
                 AND expires_at > CURRENT_TIMESTAMP""",
            (payment["user_id"],),
        ).fetchone()["expiry"]

        base_expiry = active_expiry or conn.execute(
            "SELECT CURRENT_TIMESTAMP"
        ).fetchone()[0]

        new_expiry = conn.execute(
            "SELECT datetime(?, ?)",
            (base_expiry, f"+{plan_days} days"),
        ).fetchone()[0]

        conn.execute(
            """INSERT INTO subscriptions
               (user_id, payment_ref, plan, status, expires_at)
               VALUES (?, ?, ?, 'active', ?)""",
            (payment["user_id"], payment_ref, payment["plan"], new_expiry),
        )

        conn.commit()
        return {"ok": True, "status": "successful"}, 200

    except sqlite3.IntegrityError as exc:
        conn.rollback()
        error_text = str(exc)
        if (
            "payments.provider" in error_text
            and "payments.provider_transaction_id" in error_text
        ):
            return {"ok": False, "error": "duplicate_transaction"}, 409
        return {"ok": False, "error": "confirmation_integrity_error"}, 500
    finally:
        conn.close()


@payments_bp.get("/api/payment/plans")
def payment_plans():
    return jsonify({
        "currency": "ZMW",
        "plans": [{"id": key, **value} for key, value in PLANS.items()],
    })


@payments_bp.get("/api/payments/readiness")
def payment_readiness():
    return jsonify({
        "mode": "sandbox_only",
        "payment_initiation": True,
        "live_provider_connected": False,
        "automatic_subscription_activation": False,
    })


@payments_bp.post("/api/payments/initiate")
def initiate_payment():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid_request"}), 400

    plan = data.get("plan")
    provider = data.get("provider")
    if not isinstance(plan, str) or plan not in PLANS:
        return jsonify({"ok": False, "error": "invalid_plan"}), 400

    if not isinstance(provider, str) or provider not in PROVIDERS:
        return jsonify({"ok": False, "error": "invalid_provider"}), 400

    authenticated_user = current_user()
    if authenticated_user is None:
        return jsonify({"ok": False, "error": "authentication_required"}), 401

    user_id = authenticated_user["id"]

    # Reject invalid or forged customer IDs supplied by the client.
    if "user_id" in data:
        supplied_user_id = data["user_id"]

        if type(supplied_user_id) is not int or supplied_user_id < 1:
            return jsonify({"ok": False, "error": "invalid_user"}), 400

        if supplied_user_id != user_id:
            return jsonify({"ok": False, "error": "user_mismatch"}), 403

    conn = connect_db()
    try:
        user = conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if user is None:
            return jsonify({"ok": False, "error": "unknown_user"}), 404

        payment_ref = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO payments
               (payment_ref, user_id, provider, plan, amount, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (payment_ref, user_id, provider, plan, PLANS[plan]["amount"]),
        )
        conn.commit()

        return jsonify({
            "ok": True,
            "payment_ref": payment_ref,
            "amount": PLANS[plan]["amount"],
            "currency": "ZMW",
            "status": "pending",
            "message": "Sandbox record created; no subscription activated.",
        }), 202
    finally:
        conn.close()
