# ------------------------------ Python Builder Stage ----------------------- #
FROM python:3.12-bullseye AS python-builder
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
    uv pip install gunicorn eventlet>=0.40.3 && \
    rm -rf /root/.cache

# ------------------------------ Frontend Builder Stage --------------------- #
FROM node:20-bullseye-slim AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# --------------------------------------------------------------------------- #
# ------------------------------ Production Stage --------------------------- #
FROM python:3.12-slim-bullseye AS production
# 0 – set timezone to IST (Asia/Kolkata) & install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    libopenblas0 \
    libgomp1 \
    libgfortran5 && \
    ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
# 1 – user & workdir
RUN useradd --create-home appuser
WORKDIR /app
# 2 – copy the ready-made venv and source with correct ownership
COPY --from=python-builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .
# 3 - copy built frontend from frontend-builder
COPY --from=frontend-builder --chown=appuser:appuser /app/frontend/dist /app/frontend/dist
# 4 – create required directories with proper ownership and permissions
#     Also create empty .env file with write permissions for Railway deployment
RUN mkdir -p /app/log /app/log/strategies /app/db /app/tmp /app/tmp/numba_cache /app/tmp/matplotlib /app/strategies /app/strategies/scripts /app/strategies/examples /app/keys && \
    chown -R appuser:appuser /app/log /app/db /app/tmp /app/strategies /app/keys && \
    chmod -R 755 /app/strategies /app/log /app/tmp && \
    chmod 700 /app/keys && \
    touch /app/.env && chown appuser:appuser /app/.env && chmod 666 /app/.env
# 5 – entrypoint script and fix line endings
COPY --chown=appuser:appuser start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh
# ---- RUNTIME ENVS --------------------------------------------------------- #
# Limit OpenBLAS/NumPy threads to prevent RLIMIT_NPROC exhaustion in Docker
# See: https://github.com/marketcalls/openalgo/issues/822
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    APP_MODE=standalone \
    TMPDIR=/app/tmp \
    NUMBA_CACHE_DIR=/app/tmp/numba_cache \
    LLVMLITE_TMPDIR=/app/tmp \
    MPLCONFIGDIR=/app/tmp/matplotlib \
    OPENBLAS_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 \
    NUMBA_NUM_THREADS=2
# --------------------------------------------------------------------------- #
USER appuser
EXPOSE 5000
CMD ["/app/start.sh"]
