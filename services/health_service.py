import os

import requests

HEALTH_API_URL = os.environ.get(
    'HEALTH_API_URL',
    'https://slc5duy34c.execute-api.us-east-1.amazonaws.com/Prod/calculate',
)

REQUIRED_FIELDS = ['age', 'gender', 'weight', 'height', 'activity_level', 'goal']

# Map frontend-friendly values to what the classmate API actually accepts
GOAL_MAP = {'lose': 'cut', 'gain': 'bulk'}
ACTIVITY_MAP = {'lightly_active': 'light', 'extra_active': 'very_active'}


def calculate_health_metrics(payload: dict) -> dict:
    """
    Forward a health-metrics calculation request to the classmate API.

    Expected payload keys: age, gender, weight, height, activity_level, goal
    """
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        return {'error': f'Missing required fields: {", ".join(missing)}'}

    normalized = dict(payload)
    normalized['goal'] = GOAL_MAP.get(payload.get('goal', ''), payload.get('goal', ''))
    normalized['activity_level'] = ACTIVITY_MAP.get(payload.get('activity_level', ''), payload.get('activity_level', ''))

    try:
        response = requests.post(HEALTH_API_URL, json=normalized, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {'error': 'Health metrics service timed out'}
    except requests.exceptions.HTTPError as exc:
        return {'error': f'Health metrics service returned error: {exc.response.status_code}'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Health metrics service unavailable: {exc}'}
