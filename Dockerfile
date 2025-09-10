# ------------------------------ Builder Stage ------------------------------ #
FROM python:3.12-bullseye AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .

# create isolated virtual-env with uv, then add gunicorn and eventlet with compatible versions
RUN pip install --no-cache-dir uv && \
    uv venv .venv && \
    uv pip install --upgrade pip && \
    uv sync && \
    uv pip install gunicorn eventlet==0.35.2 && \
    rm -rf /root/.cache
# --------------------------------------------------------------------------- #


# ------------------------------ Production Stage --------------------------- #
FROM python:3.12-slim-bullseye AS production

# 0 – set timezone to IST (Asia/Kolkata)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 1 – user & workdir
RUN useradd --create-home appuser
WORKDIR /app

# 2 – copy the ready-made venv and source with correct ownership
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

# 3 – create required directories with proper ownership
RUN mkdir -p /app/log /app/log/strategies /app/db /app/strategies /app/strategies/scripts /app/keys && \
    chown -R appuser:appuser /app/log /app/db /app/strategies /app/keys

# 4 – entrypoint script and fix line endings
COPY --chown=appuser:appuser start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# ---- RUNTIME ENVS --------------------------------------------------------- #
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    DOCKER_CONTAINER=true
# --------------------------------------------------------------------------- #

USER appuser
EXPOSE 5000
CMD ["/app/start.sh"]
