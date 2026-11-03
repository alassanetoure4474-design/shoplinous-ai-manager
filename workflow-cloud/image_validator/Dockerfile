FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir "mistralai-workflows>=3.10" "httpx>=0.27" "pydantic>=2.7"

CMD ["python", "-m", "src.entrypoints.worker"]
