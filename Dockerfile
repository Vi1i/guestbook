# Single-stage build using UV image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev extras)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and config
COPY README.md alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/

# Install the project itself
RUN uv sync --frozen --no-dev

# Create non-root user and data directory
RUN useradd --create-home --shell /bin/bash guestbook \
    && mkdir -p /app/data \
    && chown -R guestbook:guestbook /app /app/data

USER guestbook

EXPOSE 8000

# Default environment variables
ENV GUESTBOOK_DATABASE_URL="sqlite+aiosqlite:///./data/guestbook.db" \
    GUESTBOOK_BASE_URL="http://localhost:8000" \
    GUESTBOOK_HOST="0.0.0.0" \
    GUESTBOOK_PORT="8000"

# Run migrations then start the server
CMD ["sh", "-c", "uv run guestbook init-db && uv run guestbook run"]
