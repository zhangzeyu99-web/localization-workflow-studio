from __future__ import annotations


class UserFacingError(RuntimeError):
    """Base class for errors that can be shown to users after sanitization."""


class ProviderError(UserFacingError):
    """AI provider failed, rejected a request, or is not configured."""


class WorkflowInputError(UserFacingError):
    """User input does not match the current workflow step."""


class ArtifactError(UserFacingError):
    """Artifact is missing, invalid, or cannot be read."""


class WorkflowValidationError(UserFacingError):
    """Workflow output failed a local validation gate."""


class DeliveryError(UserFacingError):
    """Final delivery package or file generation failed."""


class UserFacingWorkflowError(UserFacingError):
    """Workflow subprocess failed with a sanitized user-facing message."""


_HTTP_STATUS_BY_ERROR_TYPE: tuple[tuple[type[UserFacingError], int], ...] = (
    (WorkflowInputError, 400),
    (ArtifactError, 404),
    (WorkflowValidationError, 422),
    (DeliveryError, 409),
    (ProviderError, 502),
    (UserFacingWorkflowError, 500),
)


def http_status_for_user_facing_error(error: UserFacingError) -> int:
    """HTTP status code for a UserFacingError raised out of a route."""
    for error_type, status in _HTTP_STATUS_BY_ERROR_TYPE:
        if isinstance(error, error_type):
            return status
    return 400
