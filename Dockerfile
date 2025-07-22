# Dockerfile for cymais-logout-service
FROM python:3.10-slim

# Build argument for container port (default 8000)
ARG LOGOUT_PORT=8000
# Expose port environment variable
ENV LOGOUT_PORT=${LOGOUT_PORT}

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py ./
COPY templates/ ./templates/

# Expose the logout service port dynamically
EXPOSE ${LOGOUT_PORT}

# Start the Flask app with Gunicorn, binding to dynamic port
CMD exec gunicorn --bind 0.0.0.0:${LOGOUT_PORT} app:app
