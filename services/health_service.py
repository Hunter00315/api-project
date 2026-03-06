import os

import requests

HEALTH_API_URL = os.environ.get(
    'HEALTH_API_URL',
    'https://slc5duy34c.execute-api.us-east-1.amazonaws.com/Prod/calculate',
)

REQUIRED_FIELDS = ['age', 'gender', 'weight', 'height', 'activity_level', 'goal']


def calculate_health_metrics(payload: dict) -> dict:
    """
    Forward a health-metrics calculation request to the classmate API.

    Expected payload keys: age, gender, weight, height, activity_level, goal
    """
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        return {'error': f'Missing required fields: {", ".join(missing)}'}

    try:
        response = requests.post(HEALTH_API_URL, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {'error': 'Health metrics service timed out'}
    except requests.exceptions.HTTPError as exc:
        return {'error': f'Health metrics service returned error: {exc.response.status_code}'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Health metrics service unavailable: {exc}'}
