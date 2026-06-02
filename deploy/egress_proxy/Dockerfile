FROM alpine:3.20

RUN apk add --no-cache tinyproxy curl

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allowlist.txt  /etc/tinyproxy/allowlist.txt

EXPOSE 8888

# -d = run in foreground (so Docker manages the process)
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
