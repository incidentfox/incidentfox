FROM python:3.11-slim

WORKDIR /app

# Copy source code and install
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Run the agent using the installed entry point
CMD ["incidentfox-k8s-agent"]
