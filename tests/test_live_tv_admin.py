import tempfile
import unittest
from pathlib import Path

import app as application


class MuviGoLiveTVAdminTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        test_db = Path(self.tmp.name) / "live_tv_test.db"

        application.app.config.update(
            DATABASE_PATH=str(test_db),
            TESTING=True,
            SECRET_KEY="test-only-secret-key",
        )

        application.init_db()

        self.admin_client = application.app.test_client()

        registered = self.admin_client.post(
            "/api/auth/register",
            json={
                "name": "Live TV Administrator",
                "email": "live-admin@test.example",
                "password": "StrongPass123",
            },
        )
        self.assertEqual(registered.status_code, 201)

        conn = application.db()
        try:
            conn.execute(
                "UPDATE users SET role = 'admin' WHERE email = ?",
                ("live-admin@test.example",),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def create_channel(self):
        return self.admin_client.post(
            "/api/admin/channels",
            json={
                "channel_id": "test-channel",
                "name": "Test Channel",
                "category": "News",
                "icon": "📺",
            },
        )

    def test_admin_can_create_pending_inactive_channel(self):
        response = self.create_channel()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json["authorization_status"],
            "pending",
        )
        self.assertEqual(response.json["feed_status"], "not_verified")
        self.assertFalse(response.json["is_active"])

        conn = application.db()
        try:
            row = conn.execute(
                """
                SELECT authorization_status, feed_status, is_active
                FROM live_channels
                WHERE channel_id = ?
                """,
                ("test-channel",),
            ).fetchone()

            self.assertEqual(row["authorization_status"], "pending")
            self.assertEqual(row["feed_status"], "not_verified")
            self.assertEqual(row["is_active"], 0)
        finally:
            conn.close()

    def test_admin_approval_requires_rights_evidence(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)
        channel_pk = created.json["channel_db_id"]

        response = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"authorization_status": "authorized"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json["error"],
            "authorization_evidence_required",
        )

    def test_feed_activation_requires_authorization_and_verification(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)
        channel_pk = created.json["channel_db_id"]

        evidence = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={
                "rights_holder": "Test Rights Holder",
                "authorization_reference": "LICENCE-TEST-001",
                "authorization_notes": "Test evidence record",
            },
        )
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(
            evidence.json["channel"]["authorization_status"],
            "pending",
        )

        approved = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"authorization_status": "authorized"},
        )
        self.assertEqual(approved.status_code, 200)

        no_url = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"feed_status": "verified"},
        )
        self.assertEqual(no_url.status_code, 409)

        url_added = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={
                "stream_url": "https://streams.example.test/live/channel.m3u8"
            },
        )
        self.assertEqual(url_added.status_code, 200)
        self.assertEqual(
            url_added.json["channel"]["feed_status"],
            "not_verified",
        )
        self.assertEqual(url_added.json["channel"]["is_active"], 0)

        verified = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"feed_status": "verified"},
        )
        self.assertEqual(verified.status_code, 200)

        activated = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"is_active": True},
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.json["channel"]["is_active"], 1)

        public_channels = self.admin_client.get("/api/channels")
        self.assertEqual(public_channels.status_code, 200)

        channel = next(
            item for item in public_channels.json
            if item["id"] == "test-channel"
        )
        self.assertTrue(channel["available"])
        self.assertEqual(
            channel["stream_url"],
            "https://streams.example.test/live/channel.m3u8",
        )

        # Changing rights evidence forces a new review and disables playback.
        changed_evidence = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"authorization_reference": "LICENCE-TEST-002"},
        )
        self.assertEqual(changed_evidence.status_code, 200)
        self.assertEqual(
            changed_evidence.json["channel"]["authorization_status"],
            "pending",
        )
        self.assertEqual(
            changed_evidence.json["channel"]["feed_status"],
            "not_verified",
        )
        self.assertEqual(changed_evidence.json["channel"]["is_active"], 0)

        public_channels = self.admin_client.get("/api/channels")
        channel = next(
            item for item in public_channels.json
            if item["id"] == "test-channel"
        )
        self.assertFalse(channel["available"])
        self.assertIsNone(channel["stream_url"])

    def test_rejects_non_https_and_non_hls_urls(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)
        channel_pk = created.json["channel_db_id"]

        http_url = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"stream_url": "http://streams.example.test/live.m3u8"},
        )
        self.assertEqual(http_url.status_code, 400)

        wrong_extension = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"stream_url": "https://streams.example.test/live.mp4"},
        )
        self.assertEqual(wrong_extension.status_code, 400)

        local_address = self.admin_client.patch(
            f"/api/admin/channels/{channel_pk}",
            json={"stream_url": "https://127.0.0.1/live.m3u8"},
        )
        self.assertEqual(local_address.status_code, 400)

    def test_admin_api_rejects_viewers_and_anonymous_users(self):
        anonymous = application.app.test_client()

        response = anonymous.get("/api/admin/channels")
        self.assertEqual(response.status_code, 401)

        viewer = application.app.test_client()
        registered = viewer.post(
            "/api/auth/register",
            json={
                "name": "Ordinary Viewer",
                "email": "viewer-live@test.example",
                "password": "StrongPass123",
            },
        )
        self.assertEqual(registered.status_code, 201)

        response = viewer.get("/api/admin/channels")
        self.assertEqual(response.status_code, 403)

        response = viewer.post(
            "/api/admin/channels",
            json={
                "channel_id": "viewer-channel",
                "name": "Viewer Channel",
                "category": "News",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_origin_channel_management_request_is_blocked(self):
        response = self.admin_client.post(
            "/api/admin/channels",
            headers={"Origin": "https://untrusted.example"},
            json={
                "channel_id": "blocked-channel",
                "name": "Blocked Channel",
                "category": "News",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["error"], "invalid_request_origin")


    def test_public_api_hides_manually_inserted_private_stream_url(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)

        conn = application.db()
        try:
            conn.execute(
                """
                UPDATE live_channels
                SET stream_url = ?,
                    authorization_status = 'authorized',
                    feed_status = 'verified',
                    is_active = 1
                WHERE channel_id = ?
                """,
                ("https://127.0.0.1/live.m3u8", "test-channel"),
            )
            conn.commit()
        finally:
            conn.close()

        response = self.admin_client.get("/api/channels")
        self.assertEqual(response.status_code, 200)

        channel = next(
            item for item in response.json
            if item["id"] == "test-channel"
        )
        self.assertFalse(channel["available"])
        self.assertIsNone(channel["stream_url"])

    def test_admin_can_delete_channel_and_preserve_audit(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)

        channel_pk = created.json["channel_db_id"]

        deleted = self.admin_client.delete(
            f"/api/admin/channels/{channel_pk}"
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json["ok"])
        self.assertEqual(deleted.json["deleted_id"], channel_pk)

        public = self.admin_client.get("/api/channels")
        self.assertEqual(public.status_code, 200)

        self.assertFalse(
            any(
                item["id"] == "test-channel"
                for item in public.json
            )
        )

        audit = self.admin_client.get("/api/admin/live-tv/audit")
        self.assertEqual(audit.status_code, 200)

        event = next(
            (
                item for item in audit.json["events"]
                if item["channel_db_id"] == channel_pk
                and item["action"] == "channel_deleted"
            ),
            None,
        )

        self.assertIsNotNone(event)

    def test_delete_missing_channel_returns_404(self):
        response = self.admin_client.delete(
            "/api/admin/channels/999999"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json["error"],
            "channel_not_found",
        )

    def test_delete_requires_admin(self):
        created = self.create_channel()
        self.assertEqual(created.status_code, 201)

        channel_pk = created.json["channel_db_id"]

        anonymous = application.app.test_client()
        response = anonymous.delete(
            f"/api/admin/channels/{channel_pk}"
        )
        self.assertEqual(response.status_code, 401)

        viewer = application.app.test_client()
        registered = viewer.post(
            "/api/auth/register",
            json={
                "name": "Delete Test Viewer",
                "email": "delete-viewer@test.example",
                "password": "StrongPass123",
            },
        )
        self.assertEqual(registered.status_code, 201)

        response = viewer.delete(
            f"/api/admin/channels/{channel_pk}"
        )
        self.assertEqual(response.status_code, 403)

        check = self.admin_client.get("/api/admin/channels")
        self.assertEqual(check.status_code, 200)


if __name__ == "__main__":
    unittest.main()
