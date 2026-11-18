import tempfile
import unittest
import uuid
from pathlib import Path

import app as application


class MediaSecurityTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "media_security.db"

        application.app.config.update(
            DATABASE_PATH=str(self.db_path),
            TESTING=True,
            SECRET_KEY="media-security-test-secret",
        )

        application.init_db()
        self.client = application.app.test_client()

        response = self.client.post(
            "/api/auth/register",
            json={
                "name": "Media Security Tester",
                "email": "media-security@example.test",
                "password": "StrongPass123",
            },
        )
        self.assertEqual(response.status_code, 201)

        conn = application.db()
        try:
            conn.execute(
                "UPDATE users SET role='admin' WHERE email=?",
                ("media-security@example.test",),
            )
            self.user_id = conn.execute(
                "SELECT id FROM users WHERE email=?",
                ("media-security@example.test",),
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        self.created_files = []

    def tearDown(self):
        for path in self.created_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

        self.tmp.cleanup()

    def create_media(self, kind, status="PUBLISHED"):
        folder = application.BASE / "media" / kind
        folder.mkdir(parents=True, exist_ok=True)

        extension = ".mp3" if kind == "music" else ".mp4"
        filename = "security_test_" + uuid.uuid4().hex + extension
        path = folder / filename
        path.write_bytes(b"MUVI GO isolated media security test")
        self.created_files.append(path)

        media_type = "music" if kind == "music" else "movie"
        relative_path = kind + "/" + filename

        conn = application.db()
        try:
            cursor = conn.execute(
                """
                INSERT INTO media
                    (title, type, category, description,
                     status, year, views, file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Security Test " + filename,
                    media_type,
                    "Security Tests",
                    "Temporary isolated security test",
                    status,
                    2026,
                    0,
                    relative_path,
                ),
            )
            conn.commit()
            return cursor.lastrowid, filename
        finally:
            conn.close()

    def add_active_subscription(self, expires_at="2099-01-01 00:00:00"):
        conn = application.db()
        try:
            conn.execute(
                """
                INSERT INTO subscriptions
                    (user_id, payment_ref, plan, status, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.user_id,
                    "MEDIA-TEST-" + uuid.uuid4().hex,
                    "monthly",
                    "active",
                    expires_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def media_url(self, kind, filename):
        return "/media-files/" + kind + "/" + filename

    def test_unauthenticated_user_cannot_access_media(self):
        _, filename = self.create_media("music")
        self.client.post("/api/auth/logout")

        response = self.client.get(self.media_url("music", filename))
        self.assertEqual(response.status_code, 401)

    def test_unpublished_music_is_not_accessible(self):
        _, filename = self.create_media("music", status="PENDING")

        response = self.client.get(self.media_url("music", filename))
        self.assertEqual(response.status_code, 404)

    def test_published_music_is_free_for_authenticated_user(self):
        _, filename = self.create_media("music")

        response = self.client.get(self.media_url("music", filename))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")

    def test_video_requires_active_subscription(self):
        _, filename = self.create_media("videos")

        response = self.client.get(self.media_url("videos", filename))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["error"], "active_subscription_required")

    def test_expired_subscription_cannot_play_video(self):
        _, filename = self.create_media("videos")
        self.add_active_subscription("2000-01-01 00:00:00")

        response = self.client.get(self.media_url("videos", filename))
        self.assertEqual(response.status_code, 403)

    def test_active_subscription_allows_published_video(self):
        _, filename = self.create_media("videos")
        self.add_active_subscription()

        response = self.client.get(self.media_url("videos", filename))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")

    def test_library_lists_published_files_only(self):
        _, published_filename = self.create_media("music", "PUBLISHED")
        _, pending_filename = self.create_media("music", "PENDING")

        response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 200)

        filenames = [item["filename"] for item in response.json]
        self.assertIn(published_filename, filenames)
        self.assertNotIn(pending_filename, filenames)

    def test_demo_video_requires_login(self):
        self.client.post("/api/auth/logout")

        response = self.client.get("/media-test.mp4")
        self.assertEqual(response.status_code, 401)

    def test_demo_video_requires_subscription(self):
        response = self.client.get("/media-test.mp4")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
