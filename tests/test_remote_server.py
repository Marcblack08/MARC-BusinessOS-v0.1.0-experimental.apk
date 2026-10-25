from __future__ import annotations

import json
import queue
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from remote_server import RemoteControlServer


class RemoteControlServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.projects_dir = self.root / "projects"
        self.db_path = self.data_dir / "marc_video_studio.db"
        self.data_dir.mkdir(parents=True)
        self.projects_dir.mkdir(parents=True)
        db = sqlite3.connect(self.db_path)
        try:
            db.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, title TEXT, topic TEXT, "
                "platform TEXT, duration_minutes INTEGER, approved INTEGER, created_at TEXT, "
                "script TEXT, style TEXT, video_mode TEXT)"
            )
            db.execute(
                "INSERT INTO projects VALUES (1, 'Proyecto de prueba', 'Una premisa', "
                "'YouTube 16:9', 2, 0, '2026-01-01T12:00:00', 'ESCENA 1: Prueba', "
                "'Misterio y suspenso', 'Corto (2 minutos)')"
            )
            db.commit()
        finally:
            db.close()
        output_dir = self.projects_dir / "1" / "exports"
        output_dir.mkdir(parents=True)
        (output_dir / "demo.mp4").write_bytes(b"fake-mp4-for-test")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.commands = queue.Queue()
        self.server = RemoteControlServer(
            data_dir=self.data_dir,
            db_path=self.db_path,
            projects_dir=self.projects_dir,
            command_queue=self.commands,
            snapshot_provider=lambda: {"label": "MARC listo", "running": False},
            host="127.0.0.1",
            port=self.port,
        )
        self.server.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.stop()
        self.temp_dir.cleanup()

    def request(self, path, *, method="GET", body=None, token=None, content_type=None):
        headers = {}
        if token is not None:
            headers["X-MARC-Token"] = token
        if content_type:
            headers["Content-Type"] = content_type
        data = body
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        return urlopen(req, timeout=4)

    def test_panel_is_served_without_exposing_api_data(self):
        with self.request("/") as response:
            content = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Panel móvil", content)
            self.assertIn("X-MARC-Token", content)
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(response.headers.get("Cross-Origin-Resource-Policy"), "same-origin")
            self.assertIn("form-action 'self'", response.headers.get("Content-Security-Policy", ""))

    def test_api_requires_private_token(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/status")
        self.assertEqual(caught.exception.code, 401)

        with self.request("/api/status", token=self.server.token) as response:
            self.assertEqual(json.loads(response.read())["label"], "MARC listo")

    def test_project_list_and_download_are_project_scoped(self):
        with self.request("/api/projects", token=self.server.token) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["projects"][0]["id"], 1)

        query = urlencode({"project_id": "1", "path": "exports/demo.mp4"})
        with self.request("/api/download?" + query, token=self.server.token) as response:
            self.assertEqual(response.read(), b"fake-mp4-for-test")
            self.assertIn("attachment;", response.headers.get("Content-Disposition", ""))

        query = urlencode({"project_id": "1", "path": "../outside.mp4"})
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/download?" + query, token=self.server.token)
        self.assertEqual(caught.exception.code, 404)

    def test_upload_is_limited_to_allowed_extensions_and_project_folder(self):
        query = urlencode({"project_id": "1", "filename": "scene.png"})
        with self.request(
            "/api/upload?" + query, method="POST", token=self.server.token,
            content_type="application/octet-stream", body=b"\\x89PNG\\r\\n\\x1a\\nvalid-test-payload",
        ) as response:
            payload = json.loads(response.read())
        self.assertTrue(payload["uploaded"])
        uploaded = self.projects_dir / "1" / payload["path"]
        self.assertTrue(uploaded.is_file())
        self.assertEqual(uploaded.read_bytes(), b"\\x89PNG\\r\\n\\x1a\\nvalid-test-payload")

        query = urlencode({"project_id": "1", "filename": "program.exe"})
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/upload?" + query, method="POST", token=self.server.token,
                content_type="application/octet-stream", body=b"not-allowed",
            )
        self.assertEqual(caught.exception.code, 415)

    def test_allowed_command_is_queued_without_touching_tk_from_http_thread(self):
        payload = json.dumps({
            "action": "generate_script",
            "payload": {"title": "Prueba", "topic": "Una historia corta"},
        }).encode("utf-8")
        with self.request(
            "/api/command", method="POST", token=self.server.token,
            content_type="application/json", body=payload,
        ) as response:
            accepted = json.loads(response.read())
        self.assertTrue(accepted["accepted"])
        command = self.commands.get_nowait()
        self.assertEqual(command["action"], "generate_script")
        self.assertEqual(command["payload"]["title"], "Prueba")

    def test_upload_rejects_extension_content_mismatch(self):
        query = urlencode({"project_id": "1", "filename": "fake.png"})
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/upload?" + query, method="POST", token=self.server.token,
                content_type="application/octet-stream", body=b"not actually a png",
            )
        self.assertEqual(caught.exception.code, 415)
        uploads = self.projects_dir / "1" / "uploads"
        self.assertFalse(uploads.exists() and any(uploads.iterdir()))

    def test_full_command_queue_returns_service_unavailable(self):
        self.commands.put_nowait({"id": "busy", "action": "generate_script", "payload": {}})
        payload = json.dumps({"action": "cancel", "payload": {}}).encode("utf-8")
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/api/command", method="POST", token=self.server.token,
                content_type="application/json", body=payload,
            )
        self.assertEqual(caught.exception.code, 503)

    def test_cancel_command_is_allowed(self):
        payload = json.dumps({"action": "cancel", "payload": {}}).encode("utf-8")
        with self.request(
            "/api/command", method="POST", token=self.server.token,
            content_type="application/json", body=payload,
        ) as response:
            self.assertEqual(response.status, 202)
        self.assertEqual(self.commands.get_nowait()["action"], "cancel")


if __name__ == "__main__":
    unittest.main()
