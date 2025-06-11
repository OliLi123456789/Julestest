# 1. Base Image
FROM python:3.10-slim

# 2. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8001
ENV HOST="0.0.0.0"
ENV APP_HOME=/app

# 3. Working Directory
WORKDIR $APP_HOME

# 4. Install System Dependencies (if any were needed, e.g., for certain Python packages)
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# 5. Install Python Dependencies
# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy Application Code
# This will copy everything from the build context (llm_chatbot_service directory)
# into /app in the image, respecting .dockerignore
COPY . .

# 7. User Management (Security Best Practice)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
# Ensure the appuser can write to log directories or any other necessary paths if applicable
# For now, assuming logs go to stdout/stderr, which is fine.
# If files were written by the app, ensure $APP_HOME is writable by appuser or specific subdirs.
# RUN chown -R appuser:appgroup $APP_HOME (Use with caution, ensure it doesn't break things)
USER appuser

# 8. Expose Port
EXPOSE $PORT

# 9. Command to Run Application
# If main.py is at $APP_HOME/main.py (due to `COPY . .` where WORKDIR is /app)
# and your service `app` is defined in `llm_chatbot_service.main`, the module path is correct.
# The structure inside the container will be /app/main.py, /app/tools/, etc.
# So, uvicorn needs to find `main.py` in the current WORKDIR /app.
CMD ["uvicorn", "main:app", "--host", "$HOST", "--port", "$PORT"]
