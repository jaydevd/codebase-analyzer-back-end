from rest_framework import status as http_status
from rest_framework.response import Response


def build_response(*, status_code: int, message: str, data=None, errors=None) -> Response:
    """Build a response that follows the project envelope."""
    payload = {
        "status": status_code,
        "data": data,
        "message": message,
    }
    if errors is not None:
        payload["errors"] = errors
    return Response(payload, status=status_code)


def success_response(message: str, data=None, status_code: int = http_status.HTTP_200_OK) -> Response:
    return build_response(status_code=status_code, message=message, data=data)


def error_response(
    message: str,
    *,
    status_code: int = http_status.HTTP_400_BAD_REQUEST,
    errors=None,
    data=None,
) -> Response:
    return build_response(status_code=status_code, message=message, data=data, errors=errors or {})
