# Dockerfile for cymais-logout-service
FROM python:3.10-slim@sha256:31dd4d9529d02d7436659061cb7564cd4733fc90e5e152709a942d53382ec8d0

# Build argument for container port (default 8000)
ARG LOGOUT_PORT=8000
# Expose port environment variable
ENV LOGOUT_PORT=${LOGOUT_PORT}

# Set working directory
WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md app.py ./
RUN pip install --no-cache-dir . \
 && pip uninstall --yes pip setuptools wheel

# Copy application code
COPY translations.yml ./
COPY templates/ ./templates/

# Expose the logout service port dynamically
EXPOSE ${LOGOUT_PORT}

# Start the Flask app with Gunicorn, binding to dynamic port
CMD ["/bin/sh", "-c", "exec gunicorn --bind 0.0.0.0:${LOGOUT_PORT} app:app"]
