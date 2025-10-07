# Deployment Guide

This directory contains deployment configurations and scripts for the Sumo Logic MCP Server in various environments.

## Quick Start

### Docker Deployment

1. **Set environment variables:**
   ```bash
   export SUMOLOGIC_ACCESS_ID="your-access-id"
   export SUMOLOGIC_ACCESS_KEY="your-access-key"
   export SUMOLOGIC_ENDPOINT="https://api.sumologic.com/api"
   ```

2. **Deploy using Docker Compose:**
   ```bash
   cd deploy
   docker-compose up -d
   ```

3. **Or use the deployment script:**
   ```bash
   ./scripts/deploy.sh
   ```

### Kubernetes Deployment

1. **Set environment variables:**
   ```bash
   export SUMOLOGIC_ACCESS_ID="your-access-id"
   export SUMOLOGIC_ACCESS_KEY="your-access-key"
   export NAMESPACE="sumologic-mcp"
   ```

2. **Deploy to Kubernetes:**
   ```bash
   ./scripts/k8s-deploy.sh
   ```

## Directory Structure

```
deploy/
├── README.md                     # This file
├── Dockerfile                    # Docker container configuration
├── .dockerignore                 # Docker ignore file
├── docker-compose.yml            # Production Docker Compose
├── docker-compose.dev.yml        # Development Docker Compose
├── scripts/
│   ├── deploy.sh                 # Docker deployment script
│   └── k8s-deploy.sh            # Kubernetes deployment script
├── kubernetes/
│   ├── deployment.yaml           # Kubernetes deployment
│   ├── service.yaml             # Kubernetes service
│   ├── configmap.yaml           # Configuration maps
│   └── secret.yaml              # Secret template
├── nginx/
│   └── nginx.conf               # Nginx reverse proxy config
└── systemd/
    ├── sumologic-mcp.service    # SystemD service file
    └── install.sh               # SystemD installation script
```

## Deployment Options

### 1. Docker Container

**Pros:**
- Easy to deploy and manage
- Consistent environment
- Good for development and testing

**Cons:**
- Single container (no high availability)
- Manual scaling

**Use Cases:**
- Development environments
- Small-scale deployments
- Testing and evaluation

### 2. Docker Compose

**Pros:**
- Multi-container orchestration
- Easy configuration management
- Built-in networking

**Cons:**
- Limited to single host
- No automatic scaling

**Use Cases:**
- Development environments
- Small production deployments
- Local testing with dependencies

### 3. Kubernetes

**Pros:**
- High availability and scaling
- Service discovery and load balancing
- Rolling updates and rollbacks
- Production-ready

**Cons:**
- More complex setup
- Requires Kubernetes knowledge

**Use Cases:**
- Production environments
- Large-scale deployments
- Multi-environment setups

### 4. SystemD Service

**Pros:**
- Native Linux integration
- System-level management
- Resource control

**Cons:**
- Platform-specific (Linux only)
- Manual dependency management

**Use Cases:**
- Traditional server deployments
- Integration with existing infrastructure
- Minimal containerization requirements

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUMOLOGIC_ACCESS_ID` | Yes | - | Sumo Logic Access ID |
| `SUMOLOGIC_ACCESS_KEY` | Yes | - | Sumo Logic Access Key |
| `SUMOLOGIC_ENDPOINT` | No | `https://api.sumologic.com/api` | Sumo Logic API endpoint |
| `SUMOLOGIC_LOG_LEVEL` | No | `INFO` | Logging level |
| `SUMOLOGIC_TIMEOUT` | No | `30` | Request timeout (seconds) |
| `SUMOLOGIC_MAX_RETRIES` | No | `3` | Maximum retry attempts |
| `SUMOLOGIC_RATE_LIMIT_DELAY` | No | `1.0` | Rate limit delay (seconds) |

### MCP Client Configuration

Choose the appropriate configuration based on your deployment method:

#### Local Python Installation
```json
{
  "mcpServers": {
    "sumologic": {
      "command": "python",
      "args": ["-m", "sumologic_mcp.main"],
      "env": {
        "SUMOLOGIC_ACCESS_ID": "your-access-id",
        "SUMOLOGIC_ACCESS_KEY": "your-access-key"
      }
    }
  }
}
```

#### Docker Container
```json
{
  "mcpServers": {
    "sumologic": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env", "SUMOLOGIC_ACCESS_ID=your-access-id",
        "--env", "SUMOLOGIC_ACCESS_KEY=your-access-key",
        "sumologic-mcp:latest"
      ]
    }
  }
}
```

#### uvx (Recommended for end users)
```json
{
  "mcpServers": {
    "sumologic": {
      "command": "uvx",
      "args": ["sumologic-mcp"],
      "env": {
        "SUMOLOGIC_ACCESS_ID": "your-access-id",
        "SUMOLOGIC_ACCESS_KEY": "your-access-key"
      }
    }
  }
}
```

## Security Considerations

### Credential Management

1. **Never hardcode credentials** in configuration files
2. **Use environment variables** or secret management systems
3. **Rotate credentials regularly**
4. **Use least-privilege access** for Sumo Logic API keys

### Network Security

1. **Use HTTPS** for all API communications
2. **Implement rate limiting** to prevent abuse
3. **Use reverse proxy** (nginx) for additional security layers
4. **Restrict network access** using firewalls or security groups

### Container Security

1. **Run as non-root user** inside containers
2. **Use minimal base images** (alpine, distroless)
3. **Scan images** for vulnerabilities regularly
4. **Keep dependencies updated**

## Monitoring and Logging

### Health Checks

The server provides health check endpoints:

```bash
# Docker
docker exec sumologic-mcp-server python -c "import sumologic_mcp; print('OK')"

# Kubernetes
kubectl exec deployment/sumologic-mcp-server -- python -c "import sumologic_mcp; print('OK')"

# Direct
curl http://localhost:8000/health
```

### Logging

Logs are available through:

```bash
# Docker
docker logs -f sumologic-mcp-server

# Kubernetes
kubectl logs -f deployment/sumologic-mcp-server

# SystemD
journalctl -u sumologic-mcp -f
```

### Metrics

Monitor these key metrics:

- **Response time**: API call latency
- **Error rate**: Failed requests percentage
- **Throughput**: Requests per second
- **Resource usage**: CPU, memory, network

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   - Verify credentials are correct
   - Check API endpoint URL
   - Ensure network connectivity to Sumo Logic

2. **Rate Limiting**
   - Increase `SUMOLOGIC_RATE_LIMIT_DELAY`
   - Reduce concurrent requests
   - Check Sumo Logic API quotas

3. **Memory Issues**
   - Increase container memory limits
   - Check for memory leaks in logs
   - Tune garbage collection settings

4. **Network Connectivity**
   - Verify DNS resolution
   - Check firewall rules
   - Test network connectivity to Sumo Logic APIs

### Debug Mode

Enable debug logging for troubleshooting:

```bash
export SUMOLOGIC_LOG_LEVEL=DEBUG
```

### Performance Issues

See [Performance Tuning Guide](../docs/performance-tuning.md) for detailed optimization recommendations.

## Backup and Recovery

### Configuration Backup

Regularly backup:
- Environment variables/configuration files
- MCP client configurations
- Deployment scripts and manifests

### Disaster Recovery

1. **Document deployment procedures**
2. **Test recovery processes regularly**
3. **Maintain infrastructure as code**
4. **Use version control for all configurations**

## Scaling

### Horizontal Scaling

For high-load scenarios:

1. **Kubernetes**: Use HorizontalPodAutoscaler
2. **Docker**: Deploy multiple containers with load balancer
3. **SystemD**: Run multiple instances on different ports

### Vertical Scaling

Increase resources:
- CPU limits for compute-intensive operations
- Memory limits for large result sets
- Network bandwidth for high-throughput scenarios

## Support

For deployment issues:

1. Check the [troubleshooting section](#troubleshooting)
2. Review logs for error messages
3. Consult the [performance tuning guide](../docs/performance-tuning.md)
4. Open an issue with deployment details and logs