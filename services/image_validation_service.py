import os

import requests

IMAGE_VALIDATION_API_URL = os.environ.get(
    'IMAGE_VALIDATION_API_URL',
    'http://54.247.232.118:8000',
)


def get_image_validation_health() -> dict:
    """Check whether the image validation API is alive."""
    try:
        response = requests.get(f'{IMAGE_VALIDATION_API_URL}/health', timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {'error': 'Image validation service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Image validation service unavailable: {exc}'}


def get_supported_formats() -> dict:
    """Return the list of accepted medical imaging formats from the classmate API."""
    try:
        response = requests.get(f'{IMAGE_VALIDATION_API_URL}/formats', timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {'error': 'Image validation service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Image validation service unavailable: {exc}'}


def validate_image(file_bytes: bytes, filename: str, content_type: str) -> dict:
    """
    Forward an uploaded file to the classmate image-validation API.

    :param file_bytes:   Raw bytes of the uploaded file
    :param filename:     Original filename (sanitised before calling this function)
    :param content_type: MIME type reported by the client upload
    :return:             Parsed JSON response from the classmate API
    """
    try:
        response = requests.post(
            f'{IMAGE_VALIDATION_API_URL}/validate-image',
            files={'file': (filename, file_bytes, content_type)},
            timeout=30,
        )
        # The classmate API returns 200 even for invalid formats; just pass
        # through the status and JSON body.
        data = response.json()
        data['_upstream_status'] = response.status_code
        return data
    except requests.exceptions.Timeout:
        return {'error': 'Image validation service timed out'}
    except requests.exceptions.RequestException as exc:
        return {'error': f'Image validation service unavailable: {exc}'}
