FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port (configurable via PORT env var)
EXPOSE 8000

# Default command
CMD ["python", "main.py"]
