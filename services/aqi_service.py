import os
from urllib.parse import quote

import requests

# WAQI (World Air Quality Index) — set WAQI_TOKEN env var for production
WAQI_TOKEN = os.environ.get('WAQI_TOKEN', 'demo')
WAQI_BASE = 'https://api.waqi.info/feed'


def get_aqi(city: str) -> dict:
    """
    Return Air Quality Index data for *city* using the WAQI API.

    Set the WAQI_TOKEN environment variable to a real token for
    production use (https://aqicn.org/api/).

    Response fields
    ───────────────
    city, station, aqi, dominance_pollutant, time, pollutants
    """
    try:
        url = f'{WAQI_BASE}/{quote(city)}/?token={WAQI_TOKEN}'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('status') != 'ok':
            return {'error': 'City not found or AQI data unavailable for this location'}

        aqi_data = data['data']
        return {
            'city': city,
            'station': aqi_data['city']['name'],
            'aqi': aqi_data['aqi'],
            'dominance_pollutant': aqi_data.get('dominentpol', 'pm25'),
            'time': aqi_data['time']['s'],
            'pollutants': {k: v.get('v') for k, v in aqi_data.get('iaqi', {}).items()},
        }
    except requests.exceptions.Timeout:
        return {'error': 'AQI service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'AQI service unavailable: {exc}'}
    except (KeyError, ValueError) as exc:
        return {'error': f'Failed to parse AQI data: {exc}'}
