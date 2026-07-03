FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
# Expose only needed dependencies for Cortex core (excluding legacy ML dependencies)
RUN pip install fastapi uvicorn[standard] httpx pydantic pydantic-settings sqlalchemy psycopg2-binary pynacl

# Copy source code
COPY backend /app/backend
COPY pytest.ini /app/pytest.ini

# Set environment
ENV PYTHONPATH=/app/backend
EXPOSE 8000

# Start server
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
