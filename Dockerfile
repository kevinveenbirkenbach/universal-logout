# Dockerfile for cymais-logout-service
FROM python:3.15-slim@sha256:2da676046630d7bf14c6764ae1143dc7fa0377a53f94bf5a642f0b214aca5bce

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
