# Performance Tuning Guide

This guide provides recommendations for optimizing the performance of the Sumo Logic MCP Server in various deployment scenarios.

## Environment Variables for Performance Tuning

### Connection and Timeout Settings

```bash
# HTTP client timeout (seconds)
SUMOLOGIC_TIMEOUT=30

# Maximum number of retry attempts for failed requests
SUMOLOGIC_MAX_RETRIES=3

# Delay between rate-limited requests (seconds)
SUMOLOGIC_RATE_LIMIT_DELAY=1.0

# Connection pool size for HTTP client
SUMOLOGIC_CONNECTION_POOL_SIZE=10

# Keep-alive timeout for HTTP connections (seconds)
SUMOLOGIC_KEEP_ALIVE_TIMEOUT=30
```

### Async and Concurrency Settings

```bash
# Maximum concurrent requests to Sumo Logic APIs
SUMOLOGIC_MAX_CONCURRENT_REQUESTS=10

# Event loop policy (auto, asyncio, uvloop)
SUMOLOGIC_EVENT_LOOP_POLICY=auto

# Worker thread pool size for blocking operations
SUMOLOGIC_THREAD_POOL_SIZE=4
```

### Caching Configuration

```bash
# Enable response caching (true/false)
SUMOLOGIC_ENABLE_CACHE=true

# Cache TTL for dashboard metadata (seconds)
SUMOLOGIC_CACHE_DASHBOARD_TTL=300

# Cache TTL for collector information (seconds)
SUMOLOGIC_CACHE_COLLECTOR_TTL=600

# Maximum cache size (number of entries)
SUMOLOGIC_CACHE_MAX_SIZE=1000
```

### Logging Performance

```bash
# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
SUMOLOGIC_LOG_LEVEL=INFO

# Enable structured JSON logging (true/false)
SUMOLOGIC_JSON_LOGGING=true

# Disable request/response logging for performance (true/false)
SUMOLOGIC_DISABLE_REQUEST_LOGGING=false
```

## Docker Performance Optimization

### Resource Limits

```yaml
# docker-compose.yml
services:
  sumologic-mcp:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

### Docker Runtime Optimizations

```dockerfile
# Use multi-stage builds to reduce image size
FROM python:3.11-slim as builder
# ... build stage

FROM python:3.11-slim as production
# ... production stage with minimal dependencies
```

### Volume Optimization

```yaml
# Use tmpfs for temporary files and logs in high-performance scenarios
volumes:
  - type: tmpfs
    target: /tmp
    tmpfs:
      size: 100M
  - type: bind
    source: ./logs
    target: /app/logs
```

## Kubernetes Performance Optimization

### Resource Requests and Limits

```yaml
# deployment.yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: sumologic-mcp-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: sumologic-mcp-server
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: sumologic-mcp-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: sumologic-mcp-server
```

## Application-Level Optimizations

### Python Runtime Optimizations

```bash
# Use uvloop for better async performance (Linux/macOS)
pip install uvloop

# Set Python optimization flags
export PYTHONOPTIMIZE=2
export PYTHONDONTWRITEBYTECODE=1
```

### Memory Management

```python
# In your configuration
import gc

# Tune garbage collection
gc.set_threshold(700, 10, 10)

# Use memory profiling in development
# pip install memory-profiler
# python -m memory_profiler your_script.py
```

### Connection Pooling

```python
# Configure httpx client with connection pooling
import httpx

client = httpx.AsyncClient(
    limits=httpx.Limits(
        max_keepalive_connections=20,
        max_connections=100,
        keepalive_expiry=30.0
    ),
    timeout=httpx.Timeout(30.0)
)
```

## Monitoring and Profiling

### Performance Metrics to Monitor

1. **Response Times**
   - API call latency
   - End-to-end request processing time
   - Queue wait times

2. **Throughput**
   - Requests per second
   - Concurrent request handling
   - Cache hit rates

3. **Resource Usage**
   - CPU utilization
   - Memory consumption
   - Network I/O
   - Disk I/O for logging

4. **Error Rates**
   - API error rates
   - Timeout occurrences
   - Rate limit hits

### Profiling Tools

```bash
# CPU profiling with py-spy
pip install py-spy
py-spy record -o profile.svg -- python -m sumologic_mcp.main

# Memory profiling with memray
pip install memray
memray run python -m sumologic_mcp.main
memray flamegraph output.bin
```

### Logging for Performance Analysis

```python
# Add performance logging
import time
import logging

logger = logging.getLogger(__name__)

async def timed_operation(operation_name):
    start_time = time.time()
    try:
        # Your operation here
        pass
    finally:
        duration = time.time() - start_time
        logger.info(f"{operation_name} completed in {duration:.3f}s")
```

## Load Testing

### Using Apache Bench (ab)

```bash
# Basic load test
ab -n 1000 -c 10 http://localhost:8000/health

# With authentication headers
ab -n 1000 -c 10 -H "Authorization: Bearer token" http://localhost:8000/api/search
```

### Using wrk

```bash
# Install wrk
# macOS: brew install wrk
# Ubuntu: sudo apt-get install wrk

# Run load test
wrk -t12 -c400 -d30s http://localhost:8000/health
```

### Using Python locust

```python
# locustfile.py
from locust import HttpUser, task, between

class SumoLogicMCPUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def health_check(self):
        self.client.get("/health")
    
    @task(3)
    def search_logs(self):
        self.client.post("/api/search", json={
            "query": "*",
            "from_time": "2024-01-01T00:00:00Z",
            "to_time": "2024-01-01T01:00:00Z"
        })

# Run: locust -f locustfile.py --host=http://localhost:8000
```

## Production Deployment Recommendations

### High Availability Setup

1. **Multiple Replicas**: Deploy at least 2-3 replicas
2. **Load Balancing**: Use a load balancer (nginx, HAProxy, or cloud LB)
3. **Health Checks**: Implement proper health check endpoints
4. **Circuit Breakers**: Use circuit breaker patterns for external API calls

### Security Considerations

```bash
# Run as non-root user
USER 1000:1000

# Use read-only filesystem where possible
--read-only --tmpfs /tmp --tmpfs /var/run

# Limit capabilities
--cap-drop=ALL --cap-add=NET_BIND_SERVICE
```

### Monitoring and Alerting

1. **Metrics Collection**: Use Prometheus + Grafana
2. **Log Aggregation**: Use ELK stack or similar
3. **Alerting**: Set up alerts for high error rates, latency, and resource usage
4. **Distributed Tracing**: Consider using OpenTelemetry for request tracing

### Backup and Recovery

1. **Configuration Backup**: Regularly backup configuration files
2. **State Management**: Ensure the server is stateless for easy recovery
3. **Disaster Recovery**: Have procedures for quick deployment in new environments

## Troubleshooting Performance Issues

### Common Performance Problems

1. **High Memory Usage**
   - Check for memory leaks in long-running operations
   - Tune garbage collection settings
   - Monitor cache sizes

2. **Slow API Responses**
   - Check Sumo Logic API status
   - Verify network connectivity and latency
   - Review rate limiting settings

3. **High CPU Usage**
   - Profile CPU-intensive operations
   - Check for inefficient loops or algorithms
   - Consider using compiled extensions for heavy computations

4. **Connection Issues**
   - Monitor connection pool usage
   - Check for connection leaks
   - Verify timeout settings

### Performance Debugging Commands

```bash
# Check container resource usage
docker stats sumologic-mcp-server

# Monitor system resources
top -p $(pgrep -f sumologic_mcp)

# Check network connections
netstat -an | grep :8000

# Monitor file descriptors
lsof -p $(pgrep -f sumologic_mcp)

# Check memory usage
ps aux | grep sumologic_mcp
```

This performance tuning guide should be regularly updated based on production experience and monitoring data.