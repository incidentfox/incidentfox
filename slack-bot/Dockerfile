FROM python:3.11-slim

WORKDIR /app

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system -e .

# Copy application code
COPY *.py .
COPY assets/ assets/
COPY templates/ templates/

# Create non-root user (OAuth tokens are now stored in config-service)
RUN useradd -m -u 1000 slackbot && \
    chown -R slackbot:slackbot /app

USER slackbot

# Run the bot
CMD ["python", "app.py"]
