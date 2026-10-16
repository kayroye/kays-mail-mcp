FROM alpine:3.22

RUN apk add --no-cache ca-certificates \
    && addgroup -g 65532 tunnel \
    && adduser -D -H -u 65532 -G tunnel tunnel

COPY tunnel-client /usr/local/bin/tunnel-client

RUN chmod 0755 /usr/local/bin/tunnel-client

USER 65532:65532

ENTRYPOINT ["/usr/local/bin/tunnel-client", "run"]
