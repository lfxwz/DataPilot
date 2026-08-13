FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels ".[postgres]"

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN python -m venv /opt/venv \
    && addgroup --system --gid 10001 datapilot \
    && adduser --system --uid 10001 --ingroup datapilot --home /nonexistent datapilot

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY scripts /app/scripts

USER 10001:10001
WORKDIR /app
EXPOSE 8000

CMD ["uvicorn", "datapilot.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
