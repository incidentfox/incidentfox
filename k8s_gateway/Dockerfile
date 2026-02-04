FROM python:3.11-slim

WORKDIR /app

# Copy source code and project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the package
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8085

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8085/health')" || exit 1

# Run the application
CMD ["uvicorn", "k8s_gateway.main:app", "--host", "0.0.0.0", "--port", "8085"]
