"""
Custom Django middleware for RAG system.
"""

import logging
import time

logger = logging.getLogger('core')


class RequestLoggingMiddleware:
    """
    Middleware for logging request/response details.
    Logs method, path, status code and response time.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()

        response = self.get_response(request)

        duration = time.time() - start_time
        duration_ms = round(duration * 1000, 2)

        # Skip logging for static files
        if not request.path.startswith('/static/'):
            logger.info(
                f"{request.method} {request.path} -> {response.status_code} "
                f"({duration_ms}ms)"
            )

        return response
