FROM python:3.12-slim

LABEL maintainer="GeoSpark Contributors"
LABEL description="GeoSpark: The Open-Source Geospatial Intelligence Protocol & Engine"

# Install system dependencies for geospatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment
ENV GDAL_CONFIG=/usr/bin/gdal-config

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[all]"

# Copy source code
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import geospark; print('ok')" || exit 1

# Default command: run the API server
CMD ["uvicorn", "geospark.api:app", "--host", "0.0.0.0", "--port", "8000"]
