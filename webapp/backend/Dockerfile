# webapp/backend/Dockerfile
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOME=/app \
    PORT=8000 \
    HOST="0.0.0.0"

WORKDIR $APP_HOME

# Assuming requirements.txt is at the root of webapp/backend
COPY ./requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code from webapp/backend into /app
COPY . .
# If main.py is in a subdirectory like 'src' or 'app', adjust the COPY and CMD path.
# e.g., COPY ./src .
# For now, assuming main.py is at $APP_HOME/main.py after 'COPY . .'

EXPOSE $PORT

# Assuming main.py at the root of the copied content contains 'app = FastAPI()'
CMD ["uvicorn", "main:app", "--host", "$HOST", "--port", "$PORT"]
