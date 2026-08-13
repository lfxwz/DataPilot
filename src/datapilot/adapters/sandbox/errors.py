"""Safe exceptions raised by generated-code execution boundaries."""


class SandboxExecutionError(RuntimeError):
    """The isolated runner failed without exposing untrusted internals."""


class GeneratedCodePolicyError(ValueError):
    """Generated code violated the static execution policy."""
