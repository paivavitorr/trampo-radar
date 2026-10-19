FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv sync --no-dev

COPY config.yaml ./

ENV DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "trampo_radar.main:app", "--host", "0.0.0.0", "--port", "8000"]
