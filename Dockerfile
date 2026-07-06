FROM python:3.12-slim

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ANDAVAR_DATA_DIR=/app/postgres_data \
    DATABASE_URL=postgresql://andavar:andavar@localhost:5432/andavar \
    PATH="/usr/lib/postgresql/17/bin:/usr/lib/postgresql/16/bin:/usr/lib/postgresql/15/bin:/usr/lib/postgresql/14/bin:${PATH}"

WORKDIR /app

# Install build deps + postgresql server and client
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    postgresql \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Make entrypoint.sh executable
RUN chmod +x entrypoint.sh

# Create the runtime user. The entrypoint starts as root only long enough to
# fix mounted volume ownership, then runs PostgreSQL and the app as 'andavar'.
RUN useradd -m -u 1001 andavar && chown -R andavar:andavar /app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
