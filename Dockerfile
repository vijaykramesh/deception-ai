FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates   && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml README.md LICENSE /app/

RUN uv venv --python 3.14
RUN uv sync --no-dev

COPY app /app/app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
