import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")

    def test_02_admin_login(self):
        res = self.client.post("/api/auth/login", json={
            "email": "admin@smartfind.ai",
            "password": "Admin@123456"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["role"], "admin")
        self.assertIn("sf_auth", res.cookies)

    def test_03_knowledge_list(self):
        res = self.client.get("/api/knowledge")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("sources", data)
        self.assertGreaterEqual(data["count"], 1)

    def test_04_keyword_search(self):
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@smartfind.ai",
            "password": "Admin@123456"
        })
        cookie = login_res.cookies.get("sf_auth")
        res = self.client.post(
            "/api/search/local",
            json={"query": "Gopal Krishna"},
            cookies={"sf_auth": cookie}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("videos", data)

    def test_05_multimodal_smart_search(self):
        res = self.client.post("/api/search/smart", json={
            "query": "SSC Chairman Gopal Krishna",
            "enableInternet": False
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("discoveryTrace", data)
        self.assertIn("local", data)

if __name__ == "__main__":
    unittest.main()
