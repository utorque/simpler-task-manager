FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY src/ ./src/
COPY chat/ ./chat/
# sandbox/tools.py backs the optional in-process fallback (CHAT_LOCAL_SANDBOX=1)
COPY sandbox/ ./sandbox/
COPY asgi.py .

# Create directory for database (app SQLite + assistant chat history)
RUN mkdir -p /app/instance

# Expose port (asgi.py serves Flask + the /assistant Chainlit app on 53000)
EXPOSE 53000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src
ENV CHAINLIT_APP_ROOT=/app/chat

# Run the application (Flask via WSGI + Chainlit, one server — see asgi.py)
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "53000"]
