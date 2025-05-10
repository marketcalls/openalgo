# ------------------------------ Builder Stage ------------------------------ #
FROM python:3.13-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .

# create isolated virtual-env with uv, then add gunicorn + eventlet
RUN pip install --no-cache-dir uv && \
    uv venv .venv && \
    uv pip install --upgrade pip && \
    uv sync && \
    uv pip install gunicorn eventlet && \
    rm -rf /root/.cache
# --------------------------------------------------------------------------- #


# ------------------------------ Production Stage --------------------------- #
FROM python:3.13-slim-bookworm AS production

# 1 – user & workdir
RUN useradd --create-home appuser
WORKDIR /app

# 2 – copy the ready-made venv and source with correct ownership
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

# 3 – entrypoint script
COPY --chown=appuser:appuser start.sh /start.sh
RUN chmod +x /start.sh

# ---- RUNTIME ENVS --------------------------------------------------------- #
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# --------------------------------------------------------------------------- #

USER appuser
EXPOSE 5000
CMD ["/start.sh"]
