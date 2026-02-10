"""
Custom exception handling for Django REST Framework.
"""

import logging

from rest_framework.views import exception_handler

logger = logging.getLogger('core')


def custom_exception_handler(exc, context):
    """Custom exception handler with logging."""
    response = exception_handler(exc, context)

    if response is not None:
        view = context.get('view', None)
        view_name = view.__class__.__name__ if view else 'Unknown'

        logger.warning(f'API Error in {view_name}: {response.status_code} - {response.data}')

        response.data = {
            'error': True,
            'status_code': response.status_code,
            'detail': response.data,
        }
    else:
        logger.error(f'Unhandled exception: {exc}', exc_info=True)

    return response
