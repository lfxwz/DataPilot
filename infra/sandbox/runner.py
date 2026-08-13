"""Trusted JSON protocol runner used inside the generated-code container."""

import io
import json
import sys
from contextlib import redirect_stdout
from types import ModuleType
from typing import Any

RESULT_MARKER = "DATAPILOT_SANDBOX_RESULT="
MAX_CAPTURED_STDOUT = 4000
MAX_RESULT_BYTES = 100_000


class _BoundedWriter(io.StringIO):
    def write(self, value: str) -> int:
        if self.tell() + len(value) > MAX_CAPTURED_STDOUT:
            raise RuntimeError("generated program exceeded the stdout limit")
        return super().write(value)


def _load_program(source: str) -> ModuleType:
    module = ModuleType("generated_analysis")
    exec(compile(source, "<generated-analysis>", "exec"), module.__dict__)
    return module


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        return _json_safe(item())
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _json_safe(tolist())
    raise TypeError(f"unsupported result type: {type(value).__name__}")


def main() -> None:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise TypeError("sandbox input must be a JSON object")
    source = payload.get("code")
    data = payload.get("data")
    if not isinstance(source, str) or not isinstance(data, list):
        raise TypeError("sandbox input requires code and a JSON record list")
    module = _load_program(source)
    analyze = getattr(module, "analyze", None)
    if not callable(analyze):
        raise TypeError("generated program does not expose analyze(data)")
    captured = _BoundedWriter()
    with redirect_stdout(captured):
        result = _json_safe(analyze(data))
    envelope = {"output": result, "stdout": captured.getvalue()}
    serialized = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    if len(serialized.encode("utf-8")) > MAX_RESULT_BYTES:
        raise RuntimeError("generated program result exceeded the JSON output limit")
    print(RESULT_MARKER + serialized)


if __name__ == "__main__":
    main()
