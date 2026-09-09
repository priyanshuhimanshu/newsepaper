FROM python:3.11-slim

WORKDIR /app

# Install only what's needed, clean up
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["gunicorn", "main:app", "-c", "gunicorn_config.py"]
