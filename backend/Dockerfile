FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
RUN adduser --disabled-password --gecos "" --uid 10001 learnflow \
    && mkdir -p /app/backend/uploads /app/backend/data/models \
    && chown -R learnflow:learnflow /app/backend/uploads /app/backend/data

USER learnflow
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
