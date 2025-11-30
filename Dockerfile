# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libvips-dev \
    libvips-tools \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create directories
RUN mkdir -p /app/tiles

# Copy requirements first for better caching
COPY pyproject.toml ./
COPY requirements.txt* ./

# Install uv for faster package installation
RUN pip install uv

# Install Python dependencies
RUN if [ -f requirements.txt ]; then uv pip install --system -r requirements.txt; else uv pip install --system -e .; fi

# Copy application files
COPY src/ ./src/
COPY run.py ./
COPY README.md ./

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app && \
    chmod -R 755 /app/tiles
USER app

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run the application with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "300", "--max-requests", "1000", "--max-requests-jitter", "100", "src.app:app"]
