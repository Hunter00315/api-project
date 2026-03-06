"""
conftest.py — shared pytest fixtures for the Healthcare API test suite.

Environment variables are set here before any application modules are
imported so that the Flask app and ReservationService use the JSON
backend (not DynamoDB) during testing.
"""
import json
import os

import pytest

# ── Must be set before importing app / services ────────────────────────────
os.environ.setdefault('USE_DYNAMODB', 'false')
os.environ.setdefault('API_KEY', 'test-api-key')


# --------------------------------------------------------------------------
TEST_SLOTS = {
    "slots": [
        {"doctor": "Dr Smith",  "time": "09:00", "available": True},
        {"doctor": "Dr Smith",  "time": "10:00", "available": True},
        {
            "doctor": "Dr Smith",
            "time": "11:00",
            "available": False,
            "patient_name": "Jane Doe",
            "reservation_id": "test-reservation-001",
            "reserved_at": "2024-01-01T10:00:00+00:00",
        },
        {"doctor": "Dr Jones",  "time": "14:00", "available": True},
        {"doctor": "Dr Jones",  "time": "15:00", "available": True},
    ]
}


@pytest.fixture()
def slots_file(tmp_path):
    """Write a fresh copy of TEST_SLOTS to a temp file before each test."""
    path = tmp_path / "slots.json"
    path.write_text(json.dumps(TEST_SLOTS))
    return str(path)


@pytest.fixture()
def client(slots_file):
    """Flask test client wired to the JSON backend with test slot data."""
    import app as app_module
    from services.reservation_service import ReservationService

    # Inject a clean service instance pointing at the temp slots file
    app_module._reservation_service = ReservationService(slots_file=slots_file)
    app_module.app.config['TESTING'] = True

    with app_module.app.test_client() as test_client:
        yield test_client

    # Reset singleton so other test sessions start fresh
    app_module._reservation_service = None


@pytest.fixture()
def auth_headers():
    return {'X-API-Key': 'test-api-key', 'Content-Type': 'application/json'}
