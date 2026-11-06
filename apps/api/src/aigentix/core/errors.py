from typing import Any


class AppError(Exception):
    """Domain error with a stable machine-readable code. Mapped to HTTP by the API layer."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class InvalidInput(AppError):
    status_code = 400
    code = "invalid_input"
