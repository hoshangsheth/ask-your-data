# Production image for the API + dashboard.
#   docker build -t ask-your-data .
#   docker run -p 8000:8000 --env-file .env ask-your-data      (SQLite demo DB, seeded on start)
# For PostgreSQL use docker-compose.yml instead.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# Dependencies first, so code changes don't invalidate this cached layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY evals ./evals

# Run as a non-root user; it only needs to write the SQLite demo database.
RUN useradd --create-home appuser && mkdir -p /srv/data && chown appuser /srv/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
