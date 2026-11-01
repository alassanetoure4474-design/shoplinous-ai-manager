FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY workflow/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY workflow/ .
CMD ["python", "worker.py"]
