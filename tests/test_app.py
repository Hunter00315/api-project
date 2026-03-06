"""
test_app.py — unit tests for the Healthcare Appointment API.

Coverage targets (per agents.md requirements):
 ✓ Slot availability check (GET /slots)
 ✓ Reservation logic      (POST /reserve)
 ✓ Cancellation           (DELETE /reserve/<id>)
 ✓ View reservations      (GET /reservations)
 ✓ Auth enforcement       (401 on missing/wrong key)
 ✓ HTTP status codes      (200, 201, 400, 401, 404, 409)
"""
import json


# =============================================================================
# Health check
# =============================================================================
class TestHealthCheck:
    def test_returns_200(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200

    def test_response_body(self, client):
        data = json.loads(resp := client.get('/health').data)
        assert data['status'] == 'healthy'


# =============================================================================
# GET /slots
# =============================================================================
class TestGetSlots:
    def test_returns_200(self, client):
        resp = client.get('/slots')
        assert resp.status_code == 200

    def test_response_has_slots_list(self, client):
        data = json.loads(client.get('/slots').data)
        assert 'slots' in data
        assert isinstance(data['slots'], list)

    def test_all_slots_returned_without_filter(self, client):
        data = json.loads(client.get('/slots').data)
        assert len(data['slots']) == 5  # matches TEST_SLOTS in conftest

    def test_filter_by_doctor(self, client):
        data = json.loads(client.get('/slots?doctor=Dr Smith').data)
        for slot in data['slots']:
            assert slot['doctor'] == 'Dr Smith'

    def test_filter_by_unknown_doctor_returns_empty_list(self, client):
        data = json.loads(client.get('/slots?doctor=Dr Nobody').data)
        assert data['slots'] == []


# =============================================================================
# POST /reserve
# =============================================================================
class TestReserveSlot:
    def test_successful_reservation_returns_201(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Smith', 'time': '09:00'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 201

    def test_successful_reservation_returns_reservation_id(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Smith', 'time': '10:00'}
        data = json.loads(client.post('/reserve', json=payload, headers=auth_headers).data)
        assert 'reservation_id' in data
        assert len(data['reservation_id']) > 0

    def test_already_booked_slot_returns_409(self, client, auth_headers):
        # Dr Smith 11:00 is pre-booked in TEST_SLOTS
        payload = {'patient_name': 'Bob', 'doctor': 'Dr Smith', 'time': '11:00'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 409

    def test_nonexistent_slot_returns_404(self, client, auth_headers):
        payload = {'patient_name': 'Bob', 'doctor': 'Dr Nobody', 'time': '99:99'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 404

    def test_missing_patient_name_returns_400(self, client, auth_headers):
        payload = {'doctor': 'Dr Smith', 'time': '09:00'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_missing_doctor_returns_400(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'time': '09:00'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_missing_time_returns_400(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Smith'}
        resp = client.post('/reserve', json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_no_api_key_returns_401(self, client):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Smith', 'time': '09:00'}
        resp = client.post('/reserve', json=payload)
        assert resp.status_code == 401

    def test_wrong_api_key_returns_401(self, client):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Smith', 'time': '09:00'}
        resp = client.post('/reserve', json=payload, headers={'X-API-Key': 'wrong-key'})
        assert resp.status_code == 401

    def test_slot_marked_unavailable_after_booking(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Jones', 'time': '14:00'}
        client.post('/reserve', json=payload, headers=auth_headers)
        # Verify slot is now unavailable
        slots_data = json.loads(client.get('/slots?doctor=Dr Jones').data)
        slot = next(s for s in slots_data['slots'] if s['time'] == '14:00')
        assert slot['available'] is False

    def test_cannot_double_book_same_slot(self, client, auth_headers):
        payload = {'patient_name': 'Alice', 'doctor': 'Dr Jones', 'time': '15:00'}
        first  = client.post('/reserve', json=payload, headers=auth_headers)
        second = client.post('/reserve', json=payload, headers=auth_headers)
        assert first.status_code == 201
        assert second.status_code == 409


# =============================================================================
# DELETE /reserve/<reservation_id>
# =============================================================================
class TestCancelReservation:
    def test_valid_cancellation_returns_200(self, client, auth_headers):
        resp = client.delete('/reserve/test-reservation-001', headers=auth_headers)
        assert resp.status_code == 200

    def test_cancellation_frees_slot(self, client, auth_headers):
        client.delete('/reserve/test-reservation-001', headers=auth_headers)
        slots_data = json.loads(client.get('/slots?doctor=Dr Smith').data)
        slot = next(s for s in slots_data['slots'] if s['time'] == '11:00')
        assert slot['available'] is True

    def test_nonexistent_reservation_id_returns_404(self, client, auth_headers):
        resp = client.delete('/reserve/does-not-exist', headers=auth_headers)
        assert resp.status_code == 404

    def test_cancel_without_api_key_returns_401(self, client):
        resp = client.delete('/reserve/test-reservation-001')
        assert resp.status_code == 401


# =============================================================================
# GET /reservations
# =============================================================================
class TestGetReservations:
    def test_returns_200(self, client, auth_headers):
        resp = client.get('/reservations', headers=auth_headers)
        assert resp.status_code == 200

    def test_returns_reservations_list(self, client, auth_headers):
        data = json.loads(client.get('/reservations', headers=auth_headers).data)
        assert 'reservations' in data
        assert isinstance(data['reservations'], list)

    def test_pre_booked_slot_appears_in_reservations(self, client, auth_headers):
        data = json.loads(client.get('/reservations', headers=auth_headers).data)
        ids = [r.get('reservation_id') for r in data['reservations']]
        assert 'test-reservation-001' in ids

    def test_filter_reservations_by_doctor(self, client, auth_headers):
        data = json.loads(
            client.get('/reservations?doctor=Dr Smith', headers=auth_headers).data
        )
        for r in data['reservations']:
            assert r['doctor'] == 'Dr Smith'

    def test_get_reservations_without_api_key_returns_401(self, client):
        resp = client.get('/reservations')
        assert resp.status_code == 401

    def test_new_booking_appears_in_reservations(self, client, auth_headers):
        client.post(
            '/reserve',
            json={'patient_name': 'Charlie', 'doctor': 'Dr Jones', 'time': '14:00'},
            headers=auth_headers,
        )
        data = json.loads(client.get('/reservations', headers=auth_headers).data)
        names = [r.get('patient_name') for r in data['reservations']]
        assert 'Charlie' in names
