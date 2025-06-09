# Dockerfile for historical-ingestor (Python)

# Use a specific Python version for reproducibility
FROM python:3.9-slim AS builder

# Set working directory
WORKDIR /app

# Install build tools if any Python packages have C extensions
# For many pure Python financial/data libraries this might not be strictly needed with slim,
# but good practice if there's uncertainty.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential gcc libffi-dev libssl-dev \
#     && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the generated protobuf files.
# This assumes that the 'common' directory (containing gen/python/market_data)
# is at the same level as the 'historical-ingestor' directory when the Docker build context is set.
# Example: If build context is 'prop-firm-platform/', then path is 'common/gen/python/market_data'.
# If build context is 'historical-ingestor/', then this path needs adjustment or protos copied differently.
# For this Dockerfile, let's assume the build context is 'historical-ingestor/' and
# we will copy the generated protobufs into a location accessible by PYTHONPATH.
# A better way is to build the protos into a wheel and install it.
# For now, direct copy:
COPY ../common/gen/python/market_data /app/market_data_protos
# The __init__.py for market_data_protos might be needed if it's treated as a package.
# Or, more simply, if historical_ingestor is structured as a package and common also,
# then relative imports or proper installation in site-packages would be used.

# Copy the historical_ingestor application code
COPY ./historical_ingestor ./historical_ingestor

# Set PYTHONPATH to include the base directory for absolute imports like 'market_data.market_data_pb2'
# and the location of our protobufs if copied as above.
ENV PYTHONPATH="/app:/app/market_data_protos"


# --- Final Stage (if no compilation needed beyond pip install) ---
# If a smaller image is desired and no build artifacts from builder stage are strictly needed beyond installed packages,
# one could just use the builder stage as the final stage, or copy only /usr/local/lib/python3.9/site-packages
# and the application code to a fresh python:3.9-slim image.
# For simplicity, using the builder stage directly as final for now.

# Define entrypoint for the application
# This allows running it like `docker run <image_name> --ticker AAPL ...`
ENTRYPOINT ["python", "-m", "historical_ingestor.main"]

# Default CMD can be empty or provide help message
CMD ["--help"]
