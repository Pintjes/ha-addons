# Exact versions: the same image at every install, a new version only when chosen and tested.
# Every library is installed already built (--only-binary): no compiler in the image, nothing
# compiled on the machine of Home Assistant (zeroconf exists built for Alpine, amd64 and aarch64).
FROM python:3.13.18-alpine3.24

RUN pip install --no-cache-dir --only-binary=:all: \
    "zeroconf==0.154.0" "ifaddr==0.2.0" "paho-mqtt==2.2.0" "websocket-client==1.9.2"

COPY *.py /
COPY web /web
COPY LICENSE /LICENSE

LABEL \
    io.hass.name="Mesh Guardian" \
    io.hass.description="Watches over your Thread / Matter network" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="Mesh Guardian" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="LicenseRef-Proprietary"

CMD [ "python3", "-u", "/watcher.py" ]
