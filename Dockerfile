# Dockerfile for cymais-logout-service
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Expose the logout service port
EXPOSE 8000

# Start the Flask app with Gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
