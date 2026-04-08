# Boost Data Collector - Docker image
# Same image runs: web (gunicorn), celery worker, celery beat

FROM python:3.11-slim

# Prevent Python from writing .pyc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# Install system deps (PostgreSQL client libs for psycopg, git for github_ops, gosu for entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    git \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy project code
COPY . .

# Create dirs that Django/settings expect (logs, staticfiles, workspace, celerybeat)
RUN mkdir -p logs staticfiles workspace celerybeat

# Entrypoint fixes volume permissions then runs CMD as appuser
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Entrypoint runs as root, chowns mounted dirs, then exec's CMD as appuser via gosu
RUN useradd --create-home appuser && chown -R appuser /app
# Git 2.35+ blocks repos when directory owner != current user; bind mounts often
# disagree (e.g. Docker Desktop on Windows). System config applies to root and appuser
# (e.g. docker exec as root vs gosu appuser in entrypoint).
RUN git config --system --add safe.directory '/app/workspace/*'
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Container starts as root so entrypoint can chown; CMD runs as appuser via gosu

# Default: run gunicorn (overridden in docker-compose for worker/beat)
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "config.wsgi:application"]
