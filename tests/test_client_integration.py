import sys
import threading
import unittest
from pathlib import Path

import httpx

from simulated_api import create_server

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from api_client import AnswerSuccess, APIClient, HealthSuccess


class LocalClientIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:" + str(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def test_health_against_real_local_server(self):
        with APIClient(base_url=self.base_url, timeout_seconds=2) as client:
            result = client.health()
        self.assertIsInstance(result, HealthSuccess)
        self.assertEqual(result.status, "ok")

    def test_known_question_against_real_local_server(self):
        with APIClient(base_url=self.base_url, timeout_seconds=2) as client:
            result = client.ask("What is Python?")
        self.assertIsInstance(result, AnswerSuccess)
        self.assertEqual(result.answer, "Python is a programming language.")
        self.assertEqual(result.source, "mock")

    def test_unknown_question_preserves_fallback(self):
        with APIClient(base_url=self.base_url, timeout_seconds=2) as client:
            result = client.ask("Where is Mars?")
        self.assertIsInstance(result, AnswerSuccess)
        self.assertIn("not in the simulated answer dictionary", result.answer)
        self.assertEqual(result.source, "mock")

    def test_malformed_question_produces_http_400(self):
        with httpx.Client(timeout=2) as client:
            response = client.post(
                self.base_url + "/ask",
                json={"question": "   "},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": "Question must be a non-empty string"},
        )


if __name__ == "__main__":
    unittest.main()
