# Multi-stage build for Python Sumo Logic MCP Server
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt requirements-dev.txt ./
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Create non-root user
RUN groupadd -r sumologic && useradd -r -g sumologic sumologic

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY sumologic_mcp/ ./sumologic_mcp/
COPY pyproject.toml ./

# Create directories for logs and config
RUN mkdir -p /app/logs /app/config && \
    chown -R sumologic:sumologic /app

# Switch to non-root user
USER sumologic

# Expose MCP server port (if applicable)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sumologic_mcp; print('OK')" || exit 1

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV SUMOLOGIC_LOG_LEVEL=INFO

# Default command
CMD ["python", "-m", "sumologic_mcp.main"]