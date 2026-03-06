import os
from urllib.parse import quote

import requests

# wttr.in provides a free, no-key-required JSON weather API
WTTR_BASE = 'https://wttr.in'


def get_weather(city: str) -> dict:
    """
    Return current weather data for *city* using the wttr.in JSON API.

    Response fields
    ───────────────
    city, temperature_c, temperature_f, feels_like_c,
    humidity, wind_speed_kmph, description
    """
    try:
        url = f'{WTTR_BASE}/{quote(city)}?format=j1'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data['current_condition'][0]
        nearest_area = data.get('nearest_area', [{}])[0]
        area_name = nearest_area.get('areaName', [{}])[0].get('value', city)

        return {
            'city': area_name,
            'query': city,
            'temperature_c': int(current['temp_C']),
            'temperature_f': int(current['temp_F']),
            'feels_like_c': int(current['FeelsLikeC']),
            'humidity_percent': int(current['humidity']),
            'wind_speed_kmph': int(current['windspeedKmph']),
            'description': current['weatherDesc'][0]['value'],
        }
    except requests.exceptions.Timeout:
        return {'error': 'Weather service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Weather service unavailable: {exc}'}
    except (KeyError, ValueError, IndexError) as exc:
        return {'error': f'Failed to parse weather data: {exc}'}
