# Stage 1: Install dependencies
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev extras)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/

# Install the project itself
RUN uv sync --frozen --no-dev

# Stage 2: Runtime
FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --shell /bin/bash guestbook

WORKDIR /app

# Copy the virtual environment and source from builder
COPY --from=builder /app /app

# Ensure data directory exists for SQLite
RUN mkdir -p /app/data && chown -R guestbook:guestbook /app/data

USER guestbook

EXPOSE 8000

# Default environment variables
ENV GUESTBOOK_DATABASE_URL="sqlite+aiosqlite:///./data/guestbook.db" \
    GUESTBOOK_BASE_URL="http://localhost:8000"

ENTRYPOINT ["uv", "run", "guestbook"]
CMD ["run", "--host", "0.0.0.0", "--port", "8000"]
