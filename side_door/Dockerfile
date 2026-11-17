FROM nginx:1.28-alpine

RUN apk add --no-cache python3 ca-certificates

COPY run.py /run.py
COPY web /web
COPY njs /njs

LABEL \
    io.hass.name="Side Door" \
    io.hass.description="Opens a web app of your local network in the Home Assistant sidebar" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="Side Door" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="GPL-3.0-or-later"

STOPSIGNAL SIGTERM
ENTRYPOINT []
CMD [ "python3", "-u", "/run.py" ]
