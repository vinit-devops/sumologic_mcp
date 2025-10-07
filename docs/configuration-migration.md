# Configuration Migration Guide

This guide helps you migrate from the reference TypeScript implementation to the Python implementation of the Sumo Logic MCP server.

## Environment Variable Mapping

The Python implementation supports both new environment variables and the original reference implementation variables for backward compatibility.

### Reference Implementation Variables (Supported)

| Reference Variable | Python Variable | Description | Default |
|-------------------|-----------------|-------------|---------|
| `SUMO_ACCESS_ID` | `SUMOLOGIC_ACCESS_ID` | Sumo Logic Access ID | Required |
| `SUMO_ACCESS_KEY` | `SUMOLOGIC_ACCESS_KEY` | Sumo Logic Access Key | Required |
| `SUMO_ENDPOINT` | `SUMOLOGIC_ENDPOINT` | Sumo Logic API endpoint | Required |
| `QUERY_TIMEOUT` | `SUMOLOGIC_QUERY_TIMEOUT` | Query timeout in seconds | 300 |
| `MAX_RESULTS` | `SUMOLOGIC_MAX_RESULTS` | Maximum results per query | 1000 |
| `DEFAULT_VMWARE_SOURCE` | `SUMOLOGIC_DEFAULT_VMWARE_SOURCE` | Default VMware source category | "otel/vmware" |

### Additional Python Implementation Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SUMOLOGIC_TIMEOUT` | HTTP request timeout in seconds | 30 |
| `SUMOLOGIC_MAX_RETRIES` | Maximum retry attempts | 3 |
| `SUMOLOGIC_RATE_LIMIT_DELAY` | Delay between rate-limited requests | 1.0 |
| `SUMOLOGIC_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO |
| `SUMOLOGIC_LOG_FORMAT` | Log format (json, text) | json |
| `SUMOLOGIC_SERVER_NAME` | MCP server name | "sumologic-mcp-server" |
| `SUMOLOGIC_SERVER_VERSION` | MCP server version | "0.1.0" |

## Migration Steps

### 1. Environment Variables

If you're using the reference implementation, you can keep your existing environment variables:

```bash
# Reference implementation (still supported)
export SUMO_ACCESS_ID="your_access_id"
export SUMO_ACCESS_KEY="your_access_key"
export SUMO_ENDPOINT="https://api.sumologic.com"
export QUERY_TIMEOUT=300
export MAX_RESULTS=1000
export DEFAULT_VMWARE_SOURCE="otel/vmware"
```

Or migrate to the new naming convention:

```bash
# Python implementation (recommended)
export SUMOLOGIC_ACCESS_ID="your_access_id"
export SUMOLOGIC_ACCESS_KEY="your_access_key"
export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"
export SUMOLOGIC_QUERY_TIMEOUT=300
export SUMOLOGIC_MAX_RESULTS=1000
export SUMOLOGIC_DEFAULT_VMWARE_SOURCE="otel/vmware"
```

### 2. Configuration File

You can also use a JSON configuration file instead of environment variables:

```json
{
  "access_id": "your_access_id",
  "access_key": "your_access_key",
  "endpoint": "https://api.sumologic.com",
  "timeout": 30,
  "max_retries": 3,
  "rate_limit_delay": 1.0,
  "log_level": "INFO",
  "log_format": "json",
  "query_timeout": 300,
  "max_results": 1000,
  "default_vmware_source": "otel/vmware"
}
```

### 3. Tool Compatibility

The Python implementation provides full backward compatibility with reference tools:

#### Reference Tools (Supported)

| Reference Tool | Python Equivalent | Status |
|---------------|-------------------|---------|
| `execute_query` | `execute_query` | ✅ Fully compatible |
| `list_metrics` | `list_metrics` | ✅ Fully compatible |
| `validate_query_syntax` | `validate_query_syntax` | ✅ Enhanced |
| `list_source_categories` | `list_source_categories` | ✅ Enhanced |
| `get_sample_data` | `get_sample_data` | ✅ Enhanced |
| `explore_vmware_metrics` | `explore_vmware_metrics` | ✅ Enhanced |

#### Enhanced Features

The Python implementation adds several enhancements while maintaining compatibility:

1. **Better Time Parsing**: Supports all reference time formats plus additional ISO 8601 and epoch formats
2. **Enhanced VMware Support**: More comprehensive VMware metrics exploration
3. **Improved Error Handling**: Better error messages and validation
4. **Performance Monitoring**: Built-in metrics and health checks
5. **Resilience Patterns**: Circuit breakers, retries, and rate limiting

### 4. MCP Client Configuration

Update your MCP client configuration to use the Python server:

#### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "sumologic": {
      "command": "python",
      "args": ["-m", "sumologic_mcp"],
      "env": {
        "SUMO_ACCESS_ID": "your_access_id",
        "SUMO_ACCESS_KEY": "your_access_key",
        "SUMO_ENDPOINT": "https://api.sumologic.com"
      }
    }
  }
}
```

#### Docker Configuration

```yaml
version: '3.8'
services:
  sumologic-mcp:
    image: sumologic-mcp-python:latest
    environment:
      - SUMO_ACCESS_ID=your_access_id
      - SUMO_ACCESS_KEY=your_access_key
      - SUMO_ENDPOINT=https://api.sumologic.com
      - QUERY_TIMEOUT=300
      - MAX_RESULTS=1000
    ports:
      - "8080:8080"
```

## Validation and Testing

### 1. Configuration Validation

The Python implementation includes comprehensive configuration validation:

```python
from sumologic_mcp.config import SumoLogicConfig

# Load and validate configuration
config = SumoLogicConfig.from_env()
validation_result = config.validate_startup_configuration()

if not validation_result["valid"]:
    for error in validation_result["errors"]:
        print(f"Error: {error['message']}")
```

### 2. Health Checks

Test your configuration with the built-in health check:

```bash
# Using the health_check tool
curl -X POST http://localhost:8080/health \
  -H "Content-Type: application/json" \
  -d '{"include_metrics": true, "include_connections": true}'
```

### 3. Tool Testing

Test reference tool compatibility:

```python
# Test execute_query (reference compatibility)
result = await search_tools.execute_query(
    query='_sourceCategory="your_category"',
    from_time="-1h",
    to_time="now",
    limit=100
)

# Test list_metrics (reference compatibility)
metrics = await metrics_tools.list_metrics(
    source_category="otel/vmware",
    limit=50
)
```

## Troubleshooting

### Common Migration Issues

1. **Environment Variable Not Found**
   - Check both reference (`SUMO_*`) and new (`SUMOLOGIC_*`) variable names
   - Use `config.validate_startup_configuration()` for detailed validation

2. **Endpoint Format Issues**
   - Ensure endpoint starts with `https://` and ends with `.sumologic.com`
   - Remove trailing slashes from endpoint URLs

3. **Tool Compatibility**
   - All reference tools are supported with the same parameters
   - Check tool names match exactly (case-sensitive)

4. **Time Format Issues**
   - Python implementation supports all reference time formats
   - Additional formats: ISO 8601, epoch seconds/milliseconds

### Getting Help

1. **Configuration Validation**: Use the built-in validation methods
2. **Health Checks**: Monitor server health with the health_check tool
3. **Logging**: Enable DEBUG logging for detailed troubleshooting
4. **Documentation**: Check the API documentation for tool schemas

## Performance Considerations

The Python implementation includes several performance improvements:

1. **Connection Pooling**: HTTP connections are pooled and reused
2. **Rate Limiting**: Built-in rate limiting prevents API quota exhaustion
3. **Circuit Breakers**: Automatic failure detection and recovery
4. **Caching**: Optional caching for frequently accessed data
5. **Monitoring**: Built-in metrics collection and monitoring

## Security Enhancements

1. **Credential Validation**: Enhanced validation of API credentials
2. **Query Sanitization**: Improved query validation and sanitization
3. **Error Handling**: Secure error messages without credential exposure
4. **Logging**: Structured logging with configurable levels

## Next Steps

1. **Test Migration**: Start with a test environment
2. **Validate Configuration**: Use validation tools to check setup
3. **Monitor Performance**: Use built-in monitoring to track performance
4. **Update Documentation**: Update your team's documentation
5. **Training**: Familiarize your team with new features and capabilities