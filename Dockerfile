FROM docker.io/library/python:3.11-alpine

# Install FFmpeg, fonts, curl, and certificates
RUN apk add --no-cache ffmpeg curl ca-certificates tzdata ttf-dejavu

WORKDIR /app

# Copy pre-downloaded mediamtx binary or download if not present
COPY bin/ /tmp/bin/
RUN if [ -f /tmp/bin/mediamtx ]; then \
        mv /tmp/bin/mediamtx /usr/local/bin/mediamtx; \
    else \
        curl -fsSL https://github.com/bluenviron/mediamtx/releases/download/v1.21.0/mediamtx_v1.21.0_linux_amd64.tar.gz | tar -xz -C /usr/local/bin mediamtx; \
    fi && \
    chmod +x /usr/local/bin/mediamtx && \
    rm -rf /tmp/bin

# Copy application files
COPY app/ /app/app/
COPY config/ /app/config/
COPY videos/ /app/videos/
COPY web/ /app/web/

# Default environment variables
ENV RTSP_PORT=8554 \
    HLS_PORT=8888 \
    WEBRTC_PORT=8889 \
    WEB_PORT=8080 \
    API_PORT=9997 \
    LOG_LEVEL=info \
    STREAMS_CONFIG_PATH=/app/config/streams.json

EXPOSE 8554 8000/udp 8001/udp 8888 8889 8189/udp 8189 8080 9997

ENTRYPOINT ["python3", "/app/app/entrypoint.py"]
