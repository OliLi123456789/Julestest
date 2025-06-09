# Dockerfile for Python custom strategy environment

# 1. Use an official Python runtime as a parent image
FROM python:3.10-slim

# 2. Set the working directory in the container
WORKDIR /app

# 3. Copy the SDK and the example user strategy into the container at /app
# The sdk.py needs to be in a place where it can be imported by user_strategy.py.
# Placing them in the same directory (/app) makes this straightforward.
COPY sdk.py .
COPY user_strategy.py .

# 4. (Optional) Install any dependencies that sdk.py or user_strategy.py might need.
# Our current sdk.py and user_strategy.py are simple and don't have external dependencies
# beyond the Python standard library. If they did, e.g., numpy or pandas:
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# 5. Specify the command to run when the container starts.
# This will execute the user_strategy.py script using python.
# The output of this script (including SDK logs) will be the container's logs.
CMD ["python", "user_strategy.py"]
