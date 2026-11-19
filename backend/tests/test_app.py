import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import URLError

from app import DEFAULT_DATABASE, create_app


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp_dir.name, "events.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "ESP32_EVENT_URL": "http://192.0.2.1/event",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def valid_event(self):
        return {
            "event_id": "event-test-001",
            "device": "sans_sensor_01",
            "event": "dog_barking",
            "description": "Cachorro latindo",
            "confidence": 0.94,
            "timestamp": "2026-11-05T22:45:00Z",
        }

    def test_health_endpoint(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "online"})

    def test_default_database_is_anchored_to_backend(self):
        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "instance",
            "events.sqlite3",
        )

        self.assertEqual(DEFAULT_DATABASE, expected)

    def test_dashboard_returns_html(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Eventos sonoros", response.data)
        self.assertIn(b"/static/app.js", response.data)
        self.assertIn(b"Demonstrar sem microfone", response.data)
        self.assertIn(b"cat_meowing", response.data)

    def test_sensor_page_is_available(self):
        response = self.client.get("/sensor")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Celular sensor", response.data)
        self.assertIn(b"/static/sensor.js", response.data)
        self.assertIn(b"microfone", response.data)

    @patch("app.urllib.request.urlopen")
    def test_simulator_forwards_event_to_esp32(self, urlopen):
        def fake_esp32_response(outgoing_request, timeout):
            sent_event = json.loads(outgoing_request.data)
            esp32_response = Mock()
            esp32_response.status = 200
            esp32_response.read.return_value = json.dumps(
                {"success": True, "event_id": sent_event["event_id"]}
            ).encode()
            context = MagicMock()
            context.__enter__.return_value = esp32_response
            return context

        urlopen.side_effect = fake_esp32_response

        response = self.client.post(
            "/api/simulate",
            json={"event": "cat_meowing"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["success"])
        self.assertTrue(response.json["event_id"])
        self.assertTrue(response.json["esp32_notified"])
        outgoing_request = urlopen.call_args.args[0]
        self.assertEqual(outgoing_request.full_url, "http://192.0.2.1/event")
        sent_event = json.loads(outgoing_request.data)
        self.assertEqual(sent_event["event"], "cat_meowing")
        self.assertIn("(simulação)", sent_event["description"])
        self.assertEqual(sent_event["event_id"], response.json["event_id"])

    def test_simulator_records_event_without_configured_esp32(self):
        self.app.config["ESP32_EVENT_URL"] = ""

        response = self.client.post(
            "/api/simulate",
            json={"event": "dog_barking"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["success"])
        self.assertFalse(response.json["esp32_notified"])
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_simulator_rejects_unsupported_event(self):
        response = self.client.post(
            "/api/simulate",
            json={"event": "unknown_sound"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["success"])

    def test_simulator_rejects_non_string_event(self):
        response = self.client.post(
            "/api/simulate",
            json={"event": ["alarm"]},
        )

        self.assertEqual(response.status_code, 400)

    @patch("app.urllib.request.urlopen", side_effect=URLError("connection refused"))
    def test_simulator_records_event_when_esp32_is_unreachable(self, _urlopen):
        response = self.client.post(
            "/api/simulate",
            json={"event": "alarm"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["success"])
        self.assertFalse(response.json["esp32_notified"])
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    @patch("app.urllib.request.urlopen")
    def test_sensor_event_records_and_notifies_esp32(self, urlopen):
        def fake_esp32_response(outbound, timeout):
            event = json.loads(outbound.data)
            response = MagicMock()
            response.status = 200
            response.read.return_value = json.dumps(
                {"success": True, "event_id": event["event_id"]}
            ).encode()
            response.__enter__.return_value = response
            self.sent = event
            return response

        urlopen.side_effect = fake_esp32_response
        response = self.client.post(
            "/api/sensor-event",
            json={
                "event_id": "sensor-event-001",
                "event": "dog_barking",
                "confidence": 0.8731,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["success"])
        self.assertTrue(response.json["esp32_notified"])
        self.assertEqual(self.sent["event_id"], response.json["event_id"])
        self.assertEqual(self.sent["device"], "sans_phone_01")
        self.assertEqual(self.sent["event"], "dog_barking")
        self.assertEqual(self.sent["confidence"], 0.87)
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    @patch("app.urllib.request.urlopen")
    def test_sensor_event_retry_does_not_duplicate_history(self, urlopen):
        def fake_esp32_response(outbound, timeout):
            event = json.loads(outbound.data)
            response = MagicMock()
            response.status = 200
            response.read.return_value = json.dumps(
                {"success": True, "event_id": event["event_id"]}
            ).encode()
            response.__enter__.return_value = response
            return response

        urlopen.side_effect = fake_esp32_response
        event = {
            "event_id": "sensor-retry-001",
            "event": "clapping",
            "confidence": 0.81,
            "timestamp": "2026-11-15T22:00:00Z",
        }

        first = self.client.post("/api/sensor-event", json=event)
        retry = self.client.post("/api/sensor-event", json=event)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_sensor_event_rejects_unknown_event(self):
        response = self.client.post(
            "/api/sensor-event",
            json={"event": "unknown_sound", "confidence": 0.9},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/events").json["events"], [])

    def test_sensor_event_rejects_non_string_event(self):
        response = self.client.post(
            "/api/sensor-event",
            json={"event": ["dog_barking"], "confidence": 0.9},
        )

        self.assertEqual(response.status_code, 400)

    def test_sensor_event_rejects_invalid_confidence(self):
        for confidence in (None, "0.9", True, 1.5, -0.1):
            response = self.client.post(
                "/api/sensor-event",
                json={"event": "clapping", "confidence": confidence},
            )
            self.assertEqual(response.status_code, 400, confidence)

    @patch("app.urllib.request.urlopen", side_effect=URLError("connection refused"))
    def test_sensor_event_stays_recorded_when_esp32_is_unreachable(self, _urlopen):
        response = self.client.post(
            "/api/sensor-event",
            json={"event": "doorbell", "confidence": 0.7},
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["success"])
        self.assertFalse(response.json["esp32_notified"])
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_tunnel_password_protects_pages_and_api(self):
        protected_app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "ACCESS_PASSWORD": "demo-password",
            }
        )
        protected_client = protected_app.test_client()

        unauthorized = protected_client.get("/")
        authorized = protected_client.get("/", auth=("sans", "demo-password"))

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)

    def test_create_and_list_event(self):
        response = self.client.post("/api/events", json=self.valid_event())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["event_id"], "event-test-001")
        self.assertTrue(response.json["success"])

        listed = self.client.get("/api/events")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json["events"]), 1)
        self.assertEqual(listed.json["events"][0]["id"], "event-test-001")
        self.assertEqual(listed.json["events"][0]["event"], "dog_barking")

    def test_event_persists_after_app_restart(self):
        response = self.client.post("/api/events", json=self.valid_event())
        self.assertEqual(response.status_code, 201)

        restarted_app = create_app(
            {"TESTING": True, "DATABASE": self.database}
        )
        restarted_client = restarted_app.test_client()
        listed = restarted_client.get("/api/events")

        self.assertEqual(len(listed.json["events"]), 1)
        self.assertEqual(listed.json["events"][0]["id"], "event-test-001")

    def test_generates_id_when_event_id_is_missing(self):
        event = self.valid_event()
        del event["event_id"]

        response = self.client.post("/api/events", json=event)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["event_id"])
        self.assertEqual(
            self.client.get("/api/events").json["events"][0]["id"],
            response.json["event_id"],
        )

    def test_rejects_malformed_json(self):
        response = self.client.post(
            "/api/events",
            data="{invalid",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["success"])

    def test_rejects_empty_body(self):
        response = self.client.post(
            "/api/events",
            data="",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["success"])

    def test_rejects_missing_required_field(self):
        event = self.valid_event()
        del event["description"]

        response = self.client.post("/api/events", json=event)

        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.json["message"])

    def test_rejects_invalid_confidence(self):
        event = self.valid_event()
        event["confidence"] = 1.2

        response = self.client.post("/api/events", json=event)

        self.assertEqual(response.status_code, 400)
        self.assertIn("confidence", response.json["message"])

    def test_retries_duplicate_event_id_idempotently(self):
        event = self.valid_event()
        first_response = self.client.post("/api/events", json=event)
        retry_response = self.client.post("/api/events", json=event)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(retry_response.status_code, 200)
        self.assertTrue(retry_response.json["success"])
        self.assertEqual(retry_response.json["event_id"], event["event_id"])
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_rejects_conflicting_duplicate_event_id(self):
        event = self.valid_event()
        self.client.post("/api/events", json=event)
        conflicting_event = {**event, "description": "Outro evento"}

        response = self.client.post("/api/events", json=conflicting_event)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json["success"])
        self.assertEqual(len(self.client.get("/api/events").json["events"]), 1)

    def test_rejects_non_json_content_type(self):
        response = self.client.post(
            "/api/events",
            data=json.dumps(self.valid_event()),
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 415)
        self.assertFalse(response.json["success"])

    def test_empty_event_list(self):
        response = self.client.get("/api/events")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"events": []})


if __name__ == "__main__":
    unittest.main()
