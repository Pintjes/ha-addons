# Exact versions: the same image at every install. paho-mqtt is installed already built
# (--only-binary): nothing compiled on the machine. The border router is reached through the
# Docker API socket, with the Python standard library: no Docker client in the image.
FROM python:3.13.18-alpine3.24

RUN pip install --no-cache-dir --only-binary=:all: "paho-mqtt==2.2.0"

COPY thread_anchor.py /
COPY LICENSE /LICENSE

LABEL \
    io.hass.name="Thread Anchor" \
    io.hass.description="Keeps your Thread network on one OMR prefix" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="Thread Anchor" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="LicenseRef-Proprietary"

CMD [ "python3", "-u", "/thread_anchor.py" ]
