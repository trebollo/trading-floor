FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts

RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 trading-floor \
    && mkdir -p /var/lib/trading-floor \
    && chown -R trading-floor:trading-floor /app /var/lib/trading-floor

USER trading-floor
ENV PYTHONPATH=/app/src

CMD ["python", "scripts/run_daily_cycle.py", "--root", "/var/lib/trading-floor", "--require-infra"]
