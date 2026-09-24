FROM debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 DISPLAY=:99
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates chromium chromium-driver xvfb x11vnc novnc openbox \
    python3 python3-aiohttp python3-selenium fonts-liberation util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 browser \
    && cp -rL /usr/share/novnc /opt/novnc
WORKDIR /app
COPY . /app
RUN chmod +x /app/driver.sh
CMD ["python3", "/app/server.py"]
