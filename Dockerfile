# build the read-only MCP server on a pinned Python base image
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
LABEL org.opencontainers.image.source="https://github.com/kayroye/kays-mail-mcp"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOME=/state XDG_DATA_HOME=/state/data
WORKDIR /app
COPY requirements.lock ./
# install only the hash-locked runtime dependencies
RUN python -m pip install pip==26.2.1 && python -m pip install --require-hashes -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# install the package before switching to its unprivileged runtime account
RUN python -m pip install --no-deps . && useradd --uid 10001 --no-create-home appuser
USER 10001:10001
EXPOSE 8700
CMD ["imap-mcp"]
