

FROM python:3.11-slim

WORKDIR /app


RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY worker.py .
COPY secrets.py .

RUN chown -R appuser:appgroup /app

USER appuser


CMD ["python", "-u", "worker.py"]
