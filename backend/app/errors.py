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
