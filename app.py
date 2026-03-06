import os
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS

from services.reservation_service import ReservationService
from services.weather_service import get_weather
from services.aqi_service import get_aqi
from services.health_service import calculate_health_metrics

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get('API_KEY', 'healthcare-api-key-2024')

# ---------------------------------------------------------------------------
# Lazy singleton — allows tests to inject a custom service instance
# ---------------------------------------------------------------------------
_reservation_service = None


def get_reservation_service():
    global _reservation_service
    if _reservation_service is None:
        _reservation_service = ReservationService()
    return _reservation_service


# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if not key or key != API_KEY:
            return jsonify({'error': 'Unauthorized — provide a valid X-API-Key header'}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health_check():
    """Service liveness check."""
    return jsonify({'status': 'healthy', 'service': 'Healthcare Appointment API'}), 200


@app.route('/slots', methods=['GET'])
def get_slots():
    """Return available appointment slots, optionally filtered by doctor."""
    doctor = request.args.get('doctor')
    slots = get_reservation_service().get_slots(doctor=doctor)
    return jsonify({'slots': slots}), 200


@app.route('/reserve', methods=['POST'])
@require_api_key
def reserve_slot():
    """Book an appointment slot."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'JSON request body required'}), 400

    required_fields = ['patient_name', 'doctor', 'time']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    result = get_reservation_service().reserve_slot(
        patient_name=data['patient_name'],
        doctor=data['doctor'],
        time=data['time'],
    )

    if result.get('error'):
        if result['error'] == 'slot_not_found':
            return jsonify({'error': 'Slot not found for the given doctor and time'}), 404
        if result['error'] == 'slot_unavailable':
            return jsonify({'error': 'Slot is already booked'}), 409
        return jsonify({'error': result['error']}), 400

    return jsonify({
        'message': 'Appointment booked successfully',
        'reservation_id': result['reservation_id'],
    }), 201


@app.route('/reserve/<reservation_id>', methods=['DELETE'])
@require_api_key
def cancel_reservation(reservation_id):
    """Cancel an existing reservation by its ID."""
    result = get_reservation_service().cancel_reservation(reservation_id)

    if result.get('error'):
        if result['error'] == 'not_found':
            return jsonify({'error': 'Reservation not found'}), 404
        return jsonify({'error': result['error']}), 400

    return jsonify({'message': 'Reservation cancelled successfully'}), 200


@app.route('/reservations', methods=['GET'])
@require_api_key
def get_reservations():
    """List all current reservations, optionally filtered by doctor."""
    doctor = request.args.get('doctor')
    reservations = get_reservation_service().get_reservations(doctor=doctor)
    return jsonify({'reservations': reservations}), 200


@app.route('/metrics', methods=['POST'])
def health_metrics():
    """Forward health-metrics payload to the classmate calculation API."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'JSON request body required'}), 400

    result = calculate_health_metrics(data)
    if result.get('error'):
        return jsonify({'error': result['error']}), 502

    return jsonify(result), 200


@app.route('/weather', methods=['GET'])
def weather():
    """Return current weather for a city (default: dublin)."""
    city = request.args.get('city', 'dublin')
    result = get_weather(city)
    if result.get('error'):
        return jsonify({'error': result['error']}), 502
    return jsonify(result), 200


@app.route('/aqi', methods=['GET'])
def aqi():
    """Return Air Quality Index data for a city (default: dublin)."""
    city = request.args.get('city', 'dublin')
    result = get_aqi(city)
    if result.get('error'):
        return jsonify({'error': result['error']}), 502
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.exception('Unhandled exception: %s', e)
    return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
