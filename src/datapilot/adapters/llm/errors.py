"""Provider errors safe for logging and API mapping."""


class LLMProviderError(RuntimeError):
    """Raised when the provider cannot return a valid structured completion."""


class LLMResponseValidationError(LLMProviderError):
    """Raised when a successful provider response violates the expected contract."""
