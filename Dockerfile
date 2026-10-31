FROM python:3.12-slim

WORKDIR /app
COPY requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt \
    && useradd --create-home --uid 10001 kambo \
    && mkdir -p /app/data \
    && chown -R kambo:kambo /app

COPY --chown=kambo:kambo server ./server
COPY --chown=kambo:kambo frontend ./frontend

USER kambo
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "server"]
