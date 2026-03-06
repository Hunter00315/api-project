import requests

GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
WEATHER_URL   = 'https://api.open-meteo.com/v1/forecast'

WMO_DESCRIPTIONS = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Icy fog',
    51: 'Light drizzle', 53: 'Moderate drizzle', 55: 'Dense drizzle',
    61: 'Slight rain', 63: 'Moderate rain', 65: 'Heavy rain',
    71: 'Slight snow', 73: 'Moderate snow', 75: 'Heavy snow',
    80: 'Slight showers', 81: 'Moderate showers', 82: 'Violent showers',
    95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with heavy hail',
}


def get_weather(city: str) -> dict:
    try:
        geo = requests.get(GEOCODING_URL, params={'name': city, 'count': 1, 'language': 'en', 'format': 'json'}, timeout=10)
        geo.raise_for_status()
        results = geo.json().get('results')
        if not results:
            return {'error': f'City not found: {city}'}

        loc = results[0]
        lat, lon = loc['latitude'], loc['longitude']
        city_name = loc.get('name', city)
        country   = loc.get('country', '')

        wx = requests.get(WEATHER_URL, params={
            'latitude': lat, 'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code',
            'wind_speed_unit': 'kmh',
        }, timeout=10)
        wx.raise_for_status()
        current = wx.json()['current']
        code = current.get('weather_code', 0)

        return {
            'city': city_name,
            'country': country,
            'query': city,
            'temperature_c': round(current['temperature_2m'], 1),
            'temperature_f': round(current['temperature_2m'] * 9 / 5 + 32, 1),
            'feels_like_c': round(current['apparent_temperature'], 1),
            'humidity_percent': current['relative_humidity_2m'],
            'wind_speed_kmph': round(current['wind_speed_10m']),
            'description': WMO_DESCRIPTIONS.get(code, f'Weather code {code}'),
        }
    except requests.exceptions.Timeout:
        return {'error': 'Weather service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Weather service unavailable: {exc}'}
    except (KeyError, ValueError, IndexError) as exc:
        return {'error': f'Failed to parse weather data: {exc}'}
