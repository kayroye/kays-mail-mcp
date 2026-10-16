# build a Keycloak image with PostgreSQL and readiness health checks enabled
FROM quay.io/keycloak/keycloak:26.8.1@sha256:79c623a22abacf3fe6c00a5fb30f5b7843d717b234033b80995891c06116d244
LABEL org.opencontainers.image.source="https://github.com/kayroye/kays-mail-mcp"
# bake production database support and health endpoints into the optimized image
RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true
