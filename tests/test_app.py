import tempfile
import unittest
from pathlib import Path

import app as application


class MuviGoSmokeTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        test_db = Path(self.tmp.name) / "test.db"

        application.app.config.update(
            DATABASE_PATH=str(test_db),
            TESTING=True,
            SECRET_KEY="test-only-secret-key",
        )

        application.init_db()
        self.client = application.app.test_client()

        # Create a test account.
        response = self.client.post(
            "/api/auth/register",
            json={
                "name": "Test Administrator",
                "email": "admin@test.example",
                "password": "StrongPass123",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Promote this isolated test account to administrator.
        conn = application.db()
        try:
            conn.execute(
                "UPDATE users SET role = 'admin' WHERE email = ?",
                ("admin@test.example",),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_home_is_muvi_go_and_has_channel_ui(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"MUVI GO", r.data)
        self.assertIn(b"channelGrid", r.data)

    def test_health_endpoint(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["service"], "MUVI GO")

    def test_search_endpoint(self):
        r = self.client.get("/api/search?q=Zambian")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            any("Zambian" in x["title"] for x in r.json)
        )

    def test_rejects_blank_media_title(self):
        r = self.client.post(
            "/api/media",
            json={"title": "  ", "type": "movie"},
        )
        self.assertEqual(r.status_code, 400)

    def test_rejects_unknown_media_type(self):
        r = self.client.post(
            "/api/media",
            json={"title": "Test", "type": "not-a-type"},
        )
        self.assertEqual(r.status_code, 400)

    def test_accepts_valid_media(self):
        r = self.client.post(
            "/api/media",
            json={"title": "Test Film", "type": "movie"},
        )
        self.assertEqual(r.status_code, 200)

        conn = application.db()
        try:
            record = conn.execute(
                "SELECT status FROM media WHERE title=?",
                ("Test Film",),
            ).fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record["status"], "PENDING")
        finally:
            conn.close()

        # Pending content must not appear in public search.
        results = self.client.get(
            "/api/search?q=Test%20Film"
        ).json
        self.assertFalse(
            any(x["title"] == "Test Film" for x in results)
        )

        # Explicit administrator publication makes it searchable.
        media_id = record_id = None
        conn = application.db()
        try:
            row = conn.execute(
                "SELECT id FROM media WHERE title=?",
                ("Test Film",),
            ).fetchone()
            media_id = row["id"]
        finally:
            conn.close()

        update = self.client.patch(
            f"/api/media/{media_id}",
            json={"status": "PUBLISHED"},
        )
        self.assertEqual(update.status_code, 200)

        results = self.client.get(
            "/api/search?q=Test%20Film"
        ).json
        self.assertTrue(
            any(x["title"] == "Test Film" for x in results)
        )

    def test_admin_dashboard_shows_workflow_statistics(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total catalogue", response.data)
        self.assertIn(b"Pending review", response.data)
        self.assertIn(b"Rights check", response.data)


    def test_v5_admin_can_edit_media_and_reject_missing_id(self):
        created = self.client.post(
            "/api/media",
            json={"title": "V5 Edit Test", "type": "movie"},
        )
        self.assertEqual(created.status_code, 200)

        conn = application.db()
        try:
            row = conn.execute(
                "SELECT id FROM media WHERE title=?",
                ("V5 Edit Test",),
            ).fetchone()
            self.assertIsNotNone(row)
            media_id = row["id"]
        finally:
            conn.close()

        updated = self.client.patch(
            f"/api/media/{media_id}",
            json={"title": "V5 Edited Test", "status": "INACTIVE"},
        )
        self.assertEqual(updated.status_code, 200)

        conn = application.db()
        try:
            row = conn.execute(
                "SELECT title, status FROM media WHERE id=?",
                (media_id,),
            ).fetchone()
            self.assertEqual(row["title"], "V5 Edited Test")
            self.assertEqual(row["status"], "INACTIVE")
        finally:
            conn.close()

        missing = self.client.patch(
            "/api/media/999999999",
            json={"title": "Should Not Exist"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_v5_admin_can_delete_media_and_missing_id_is_rejected(self):
        created = self.client.post(
            "/api/media",
            json={"title": "V5 Delete Test", "type": "movie"},
        )
        self.assertEqual(created.status_code, 200)

        conn = application.db()
        try:
            row = conn.execute(
                "SELECT id FROM media WHERE title=?",
                ("V5 Delete Test",),
            ).fetchone()
            self.assertIsNotNone(row)
            media_id = row["id"]
        finally:
            conn.close()

        deleted = self.client.delete(f"/api/media/{media_id}")
        self.assertEqual(deleted.status_code, 200)

        conn = application.db()
        try:
            row = conn.execute(
                "SELECT id FROM media WHERE id=?",
                (media_id,),
            ).fetchone()
            self.assertIsNone(row)
        finally:
            conn.close()

        repeated = self.client.delete(f"/api/media/{media_id}")
        self.assertEqual(repeated.status_code, 404)

    def test_v5_admin_dashboard_requires_login(self):
        with self.client.session_transaction() as session:
            session.clear()

        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "login_required")

    def test_v5_dashboard_exposes_management_controls(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)

        for expected in (
            b'id="mediaSearch"',
            b'data-filter="all"',
            b'edit-media',
            b'delete-media',
            b'id="editMediaForm"',
            b'id="cancelMediaEdit"',
        ):
            with self.subTest(control=expected):
                self.assertIn(expected, response.data)


if __name__ == "__main__":
    unittest.main()
