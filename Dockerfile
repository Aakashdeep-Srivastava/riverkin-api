# syntax=docker/dockerfile:1

# ---- Builder: resolve & install deps with uv into a venv ----
FROM python:3.12-slim AS builder

# uv binary from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install dependencies first (cached layer) using the committed lockfile.
COPY pyproject.toml uv.lock ./
RUN uv venv /opt/venv \
    && uv sync --frozen --no-install-project --no-dev

# Now copy the source and install the project itself.
COPY . .
RUN uv sync --frozen --no-dev

# ---- Runtime: slim image, non-root ----
FROM python:3.12-slim AS runtime

# Runtime libs needed by opencv-python-headless.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . .

# Non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Run migrations once, then serve. Keep the API at 1 replica during the
# hackathon so migrations never run twice (CLAUDE.md).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
