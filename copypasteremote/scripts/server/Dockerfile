# CopyPasteRemote orchestrator image.
# Build from the repository root:
#   docker build -t copypasteremote -f scripts/server/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# Install server dependencies first (better layer caching).
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy the application code.
COPY cpr_shared ./cpr_shared
COPY cpr_server ./cpr_server
COPY run_server.py ./

# Data (SQLite + blobs) lives here; mount a volume to persist it.
ENV CPR_DATA_DIR=/data
ENV CPR_HOST=0.0.0.0
ENV CPR_PORT=8765
VOLUME ["/data"]
EXPOSE 8765

# TLS is typically terminated by a reverse proxy in front of the container.
CMD ["python", "run_server.py"]
