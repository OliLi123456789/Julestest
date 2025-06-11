# Dockerfile for Python custom strategy environment

# 1. Use an official Python runtime as a parent image
FROM python:3.10-slim

# 2. Set the working directory in the container
WORKDIR /app

# 3. Copy SDK first (its base requirements could be installed here if it had any)
# For this project, sdk.py itself doesn't have external pip dependencies beyond what's in the base python image (like pandas for CSV reading)
# If sdk.py itself had a requirements_sdk.txt:
# COPY requirements_sdk.txt .
# RUN if [ -f requirements_sdk.txt ]; then pip install --no-cache-dir -r requirements_sdk.txt; fi
COPY sdk.py .

# 4. Copy user strategy and their specific requirements file
# These files are expected to be in the build context (e.g., custom_env/python/)
# run_python_strategy.sh will ensure strategy_requirements.txt exists (even if empty)
# before docker build is called, so COPY will not fail.
COPY user_strategy.py .
COPY strategy_requirements.txt .
COPY cde_runner.py . # Added: Copy the CDE runner

# 5. Install user strategy dependencies if strategy_requirements.txt exists and is not empty
#    The `COPY strategy_requirements.txt .` ensures the file is present.
#    pip handles an empty requirements file gracefully (does nothing).
RUN echo "Checking and installing user strategy dependencies from strategy_requirements.txt..." && \
    pip install --no-cache-dir -r strategy_requirements.txt && \
    echo "Finished processing strategy_requirements.txt."

# 6. (Optional) Install any other common data science packages if the base image is too slim
#    For example, if strategies frequently use numpy/pandas and they weren't in a shared requirements_sdk.txt
#    RUN pip install --no-cache-dir numpy pandas
#    (Note: pandas was added to sdk.py, so it should be included directly or via requirements_sdk.txt if sdk.py gets its own)
#    For now, assuming pandas is brought in by user_strategy.py or a common SDK req file if formalized.
#    The current sdk.py imports pandas, so it needs to be available.
#    Let's add pandas here as a common dependency for the SDK for now.
RUN pip install --no-cache-dir pandas python-json-logger PyYAML

# 7. Specify the command to run when the container starts.
#    The CDE runner will now be the main entry point.
#    It expects config path and strategy details, potentially via ENV vars or cmd args.
#    For simplicity, assume cde_runner.py loads a default config or one specified by ENV var.
CMD ["python", "cde_runner.py"]
