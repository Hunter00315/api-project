import requests

GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
AQI_URL = 'https://air-quality-api.open-meteo.com/v1/air-quality'

_AQI_POLLUTANTS = 'pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone,sulphur_dioxide,us_aqi'

_DOMINANT_ORDER = ['pm2_5', 'pm10', 'ozone', 'nitrogen_dioxide', 'sulphur_dioxide', 'carbon_monoxide']


def _dominant_pollutant(pollutants: dict) -> str:
    """Return the pollutant key with the highest concentration (excluding us_aqi)."""
    candidates = {k: v for k, v in pollutants.items() if v is not None and k != 'us_aqi'}
    if not candidates:
        return 'pm2_5'
    return max(candidates, key=lambda k: candidates[k])


def get_aqi(city: str) -> dict:
    """
    Return Air Quality Index data for *city* using the Open-Meteo Air Quality API.
    No API key required. Geocodes the city name first, then fetches real-time AQI.

    Response fields
    ───────────────
    city, station, aqi, dominance_pollutant, time, pollutants
    """
    try:
        # Step 1: Geocode city name → lat/lon
        geo_resp = requests.get(
            GEOCODING_URL,
            params={'name': city, 'count': 1, 'language': 'en'},
            timeout=10,
        )
        geo_resp.raise_for_status()
        geo_results = geo_resp.json().get('results')
        if not geo_results:
            return {'error': f'City "{city}" not found'}

        location = geo_results[0]
        lat = location['latitude']
        lon = location['longitude']
        city_name = location.get('name', city)
        country = location.get('country', '')

        # Step 2: Fetch air quality data
        aqi_resp = requests.get(
            AQI_URL,
            params={
                'latitude': lat,
                'longitude': lon,
                'current': _AQI_POLLUTANTS,
                'timezone': 'auto',
            },
            timeout=10,
        )
        aqi_resp.raise_for_status()
        aqi_data = aqi_resp.json()

        current = aqi_data.get('current', {})
        us_aqi = current.get('us_aqi')

        pollutants = {}
        for key in ['pm10', 'pm2_5', 'carbon_monoxide', 'nitrogen_dioxide', 'ozone', 'sulphur_dioxide']:
            val = current.get(key)
            if val is not None:
                pollutants[key] = round(val, 1)

        return {
            'city': city,
            'station': f'{city_name}, {country}',
            'aqi': us_aqi,
            'dominance_pollutant': _dominant_pollutant(pollutants),
            'time': current.get('time', ''),
            'pollutants': pollutants,
        }
    except requests.exceptions.Timeout:
        return {'error': 'AQI service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'AQI service unavailable: {exc}'}
    except Exception as exc:
        return {'error': f'Failed to parse AQI data: {exc}'}
