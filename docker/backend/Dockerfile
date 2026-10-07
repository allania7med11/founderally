# One image for the API, the workers and the migration command.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies first, so a code change does not rebuild them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ .
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "logging.json"]
