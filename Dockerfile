# Dockerfile for cymais-logout-service
FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377

# Build argument for container port (default 8000)
ARG LOGOUT_PORT=8000
# Expose port environment variable
ENV LOGOUT_PORT=${LOGOUT_PORT}

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
 && pip uninstall --yes pip setuptools wheel \
 && groupadd --system --gid 10001 logout \
 && useradd --system --uid 10001 --gid logout --no-create-home --shell /usr/sbin/nologin logout

# Copy application code
COPY app.py gate.py translations.yml ./
COPY templates/ ./templates/

USER 10001:10001

# Expose the logout service port dynamically
EXPOSE ${LOGOUT_PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:' + os.environ['LOGOUT_PORT'] + '/', timeout=4)"]

# Start the Flask app with Gunicorn, binding to dynamic port
CMD ["/bin/sh", "-c", "exec gunicorn --bind 0.0.0.0:${LOGOUT_PORT} --worker-class gthread --threads 8 app:app"]
