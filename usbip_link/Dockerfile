# Exact versions: the same image at every install. usbip (attach, port, list) comes from Alpine,
# paho-mqtt is installed already built (--only-binary): nothing compiled on the machine.
FROM python:3.13.18-alpine3.24

RUN apk add --no-cache "linux-tools-usbip=7.1.5-r0" kmod hwids-usb \
    && pip install --no-cache-dir --only-binary=:all: "paho-mqtt==2.2.0"

COPY usbip_link.py /

LABEL \
    io.hass.name="USB/IP Link" \
    io.hass.description="Uses the USB devices of another computer and keeps them attached" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="USB/IP Link" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="GPL-3.0-or-later"

CMD [ "python3", "-u", "/usbip_link.py" ]
