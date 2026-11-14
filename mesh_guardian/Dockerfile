FROM python:3.13-alpine

RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip install --no-cache-dir "zeroconf>=0.136,<1" "paho-mqtt>=2.1,<3" "websocket-client>=1.8,<2" \
    && apk del .build-deps

COPY watcher.py healer.py radio.py labels.py advice.py matterlive.py nodetable.py quality.py history.py report.py storm.py webui.py reattach.py i18n.py /
COPY web /web

LABEL \
    io.hass.name="Mesh Guardian" \
    io.hass.description="Watches over your Thread / Matter network" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="Mesh Guardian" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="GPL-3.0-or-later"

CMD [ "python3", "-u", "/watcher.py" ]
