FROM registry.atlan.com/public/application-sdk:main-2.3.1

COPY --chown=appuser:appuser pyproject.toml README.md ./
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv venv .venv && \
    uv sync --no-install-project

COPY --chown=appuser:appuser . .

ENV ATLAN_APP_HTTP_PORT=8000

RUN uv run poe download-components
