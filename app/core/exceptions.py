"""Custom exceptions. Messages are safe to show to end users."""


class AppError(Exception):
    status_code = 400
    code = "app_error"
    transient = False

    def __init__(self, message: str = "", *, transient: bool | None = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or "Request failed"
        if transient is not None:
            self.transient = transient


class AuthenticationError(AppError):
    status_code, code = 401, "authentication_failed"


class AuthorizationError(AppError):
    status_code, code = 403, "forbidden"


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class ConflictError(AppError):
    status_code, code = 409, "conflict"


class ValidationAppError(AppError):
    status_code, code = 422, "validation_error"


class RateLimitError(AppError):
    status_code, code = 429, "rate_limited"


class IntegrationNotConfigured(AppError):
    status_code, code = 501, "integration_not_configured"


class JobSourceError(AppError):
    status_code, code = 502, "job_source_error"


class ResumeParsingError(AppError):
    status_code, code = 422, "resume_parsing_error"


class LLMError(AppError):
    status_code, code = 502, "llm_error"


class EmbeddingError(AppError):
    status_code, code = 502, "embedding_error"


class MatchingError(AppError):
    status_code, code = 500, "matching_error"


class DocumentGenerationError(AppError):
    status_code, code = 500, "document_generation_error"


class ApplicationError(AppError):
    status_code, code = 400, "application_error"
