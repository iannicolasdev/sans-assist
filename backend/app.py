import datetime
import hmac
import json
import math
import os
import sqlite3
import urllib.error
import urllib.request
import uuid

from flask import Flask, Response, current_app, g, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, UnsupportedMediaType


SIMULATED_EVENTS = {
    "doorbell": "Campainha tocando (simulação)",
    "dog_barking": "Cachorro latindo (simulação)",
    "cat_meowing": "Miado de gato (simulação)",
    "clapping": "Palmas (simulação)",
    "alarm": "Alarme (simulação)",
}

SENSOR_EVENTS = {
    "doorbell": "Campainha tocando",
    "dog_barking": "Cachorro latindo",
    "cat_meowing": "Miado de gato",
    "clapping": "Palmas",
    "alarm": "Alarme",
}

DEFAULT_DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "instance",
    "events.sqlite3",
)


def persist_event(payload):
    db = get_db()
    existing = db.execute(
        "SELECT payload_json FROM events WHERE id = ?",
        (payload["event_id"],),
    ).fetchone()
    if existing is not None:
        if json.loads(existing["payload_json"]) == payload:
            return 200, "Event already registered"
        return 409, "An event with this event_id has different data"

    try:
        db.execute(
            """
            INSERT INTO events (
                id, device, event, description, confidence, timestamp, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["event_id"],
                payload["device"],
                payload["event"],
                payload["description"],
                payload["confidence"],
                payload["timestamp"],
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return 409, "An event with this event_id is already registered"

    return 201, "Event registered"


def notify_esp32(event):
    esp32_event_url = current_app.config["ESP32_EVENT_URL"]
    if not esp32_event_url:
        current_app.logger.warning("ESP32 event URL is not configured.")
        return False

    outbound_request = urllib.request.Request(
        esp32_event_url,
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(outbound_request, timeout=5) as response:
            status_code = response.status
            response_body = response.read()
    except urllib.error.HTTPError as error:
        status_code = error.code
        response_body = error.read()
    except (urllib.error.URLError, TimeoutError) as error:
        current_app.logger.warning("Could not reach ESP32 event endpoint: %s", error)
        return False

    try:
        esp32_response = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        esp32_response = {}

    notified = (
        200 <= status_code < 300
        and isinstance(esp32_response, dict)
        and esp32_response.get("success") is True
        and esp32_response.get("event_id") == event["event_id"]
    )
    if not notified:
        current_app.logger.warning(
            "ESP32 did not confirm event %s (HTTP %s)",
            event["event_id"],
            status_code,
        )
    return notified


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=DEFAULT_DATABASE,
        ESP32_EVENT_URL=os.environ.get("SANS_ESP32_EVENT_URL", ""),
        ACCESS_PASSWORD=os.environ.get("SANS_ACCESS_PASSWORD", ""),
        MAX_CONTENT_LENGTH=4096,
    )

    if test_config:
        app.config.update(test_config)

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    with app.app_context():
        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                device TEXT NOT NULL,
                event TEXT NOT NULL,
                description TEXT NOT NULL,
                confidence REAL NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        db.commit()

    @app.errorhandler(BadRequest)
    def handle_bad_request(_error):
        return jsonify(success=False, message="Request body must contain valid JSON"), 400

    @app.errorhandler(UnsupportedMediaType)
    def handle_unsupported_media_type(_error):
        return jsonify(success=False, message="Content-Type must be application/json"), 415

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error):
        return jsonify(success=False, message="Request body is too large"), 413

    @app.before_request
    def require_tunnel_password():
        password = current_app.config["ACCESS_PASSWORD"]
        if not password:
            return None

        credentials = request.authorization
        if (
            credentials
            and credentials.username == "sans"
            and hmac.compare_digest(
                (credentials.password or "").encode("utf-8"),
                password.encode("utf-8"),
            )
        ):
            return None

        return Response(
            "Acesso restrito para esta demonstração.",
            401,
            {"WWW-Authenticate": 'Basic realm="SANS", charset="UTF-8"'},
        )

    @app.post("/api/events")
    def create_event():
        if not request.is_json:
            return jsonify(success=False, message="Content-Type must be application/json"), 415

        payload = request.get_json()
        if not isinstance(payload, dict):
            return jsonify(success=False, message="Request body must be a JSON object"), 400

        required_strings = ("device", "event", "description", "timestamp")
        for field in required_strings:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                return jsonify(
                    success=False,
                    message=f"'{field}' must be a non-empty string",
                ), 400

        confidence = payload.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
            or not math.isfinite(confidence)
        ):
            return jsonify(
                success=False,
                message="'confidence' must be a number between 0 and 1",
            ), 400

        supplied_id = payload.get("event_id")
        if supplied_id is not None and (
            not isinstance(supplied_id, str) or not supplied_id.strip()
        ):
            return jsonify(
                success=False,
                message="'event_id' must be a non-empty string when provided",
            ), 400

        event_id = supplied_id or str(uuid.uuid4())
        payload = {**payload, "event_id": event_id}
        status_code, message = persist_event(payload)
        if status_code == 409:
            return jsonify(success=False, event_id=event_id, message=message), 409

        return jsonify(
            success=True,
            event_id=event_id,
            message=message,
        ), status_code

    @app.get("/api/events")
    def list_events():
        rows = get_db().execute(
            """
            SELECT id, device, event, description, confidence, timestamp
            FROM events
            ORDER BY rowid DESC
            """
        ).fetchall()
        return jsonify(
            events=[
                {
                    "id": row["id"],
                    "device": row["device"],
                    "event": row["event"],
                    "description": row["description"],
                    "confidence": row["confidence"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ]
        )

    @app.post("/api/simulate")
    def simulate_event():
        if not request.is_json:
            return jsonify(success=False, message="Content-Type must be application/json"), 415

        payload = request.get_json()
        if not isinstance(payload, dict):
            return jsonify(success=False, message="Request body must be a JSON object"), 400

        event_type = payload.get("event")
        if not isinstance(event_type, str) or event_type not in SIMULATED_EVENTS:
            return jsonify(
                success=False,
                message="Choose a supported simulated event",
            ), 400

        event = {
            "event_id": str(uuid.uuid4()),
            "device": "sans_sensor_01",
            "event": event_type,
            "description": SIMULATED_EVENTS[event_type],
            "confidence": 0.94,
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
        return record_and_notify(event)

    @app.post("/api/sensor-event")
    def sensor_event():
        if not request.is_json:
            return jsonify(success=False, message="Content-Type must be application/json"), 415

        payload = request.get_json()
        if not isinstance(payload, dict):
            return jsonify(success=False, message="Request body must be a JSON object"), 400

        event_type = payload.get("event")
        if not isinstance(event_type, str) or event_type not in SENSOR_EVENTS:
            return jsonify(success=False, message="Unsupported sound event"), 400

        confidence = payload.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            return jsonify(
                success=False,
                message="'confidence' must be a number between 0 and 1",
            ), 400

        event_id = payload.get("event_id", str(uuid.uuid4()))
        if not isinstance(event_id, str) or not event_id.strip():
            return jsonify(
                success=False,
                message="'event_id' must be a non-empty string",
            ), 400

        timestamp = payload.get("timestamp")
        if timestamp is not None and (
            not isinstance(timestamp, str) or not timestamp.strip()
        ):
            return jsonify(
                success=False,
                message="'timestamp' must be a non-empty string",
            ), 400

        event = {
            "event_id": event_id,
            "device": "sans_phone_01",
            "event": event_type,
            "description": SENSOR_EVENTS[event_type],
            "confidence": round(float(confidence), 2),
            "timestamp": timestamp
            or datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
        return record_and_notify(event)

    def record_and_notify(event):
        status_code, message = persist_event(event)
        if status_code == 409:
            return jsonify(
                success=False,
                event_id=event["event_id"],
                message=message,
            ), 409

        notified = notify_esp32(event)
        if notified:
            message = "Event recorded and ESP32 notified."
        else:
            message = "Event recorded, but the ESP32 was not notified. Check its connection."

        return jsonify(
            success=True,
            event_id=event["event_id"],
            esp32_notified=notified,
            message=message,
        ), status_code

    @app.get("/api/health")
    def health():
        get_db().execute("SELECT 1").fetchone()
        return jsonify(status="online")

    @app.get("/")
    def dashboard():
        return render_template("index.html")

    @app.get("/sensor")
    def sensor_page():
        return render_template("sensor.html")

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
