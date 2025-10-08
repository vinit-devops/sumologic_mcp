# Sumo Logic MCP Python Server

A Python implementation of a Model Context Protocol (MCP) server for Sumo Logic API integration. This server provides a comprehensive interface to Sumo Logic's REST APIs through the MCP protocol, enabling seamless integration with MCP-compatible clients.

## Features

This MCP server provides tools to interact with Sumo Logic's APIs, allowing users to:

### 🔍 Search & Analytics
- Execute log search queries with flexible parameters
- Monitor search job status and retrieve results
- Support for pagination and result limiting

### 📊 Dashboard Management
- List, create, update, and delete dashboards
- Retrieve dashboard configurations and metadata
- Manage dashboard panels and visualizations

### 📈 Metrics & Monitoring
- Query time-series metrics data
- Support for metric selectors and aggregations
- List available metric sources

### 🔧 Collector & Source Management
- Manage collectors (list, create, update, delete)
- Configure data sources within collectors
- Monitor collector status and health

## Requirements

- Python 3.8 or higher
- Sumo Logic account with API access
- Valid Sumo Logic Access ID and Access Key

## Installation

### From PyPI (published)
```bash
pip install sumologic-mcp-python
```

### From Source
1. Clone the repository:
```bash
git clone https://github.com/sumologic/sumologic-mcp-python.git
cd sumologic-mcp-python
```

2. Install the package:
```bash
pip install -e .
```

### Development Installation
For development with all dependencies:
```bash
pip install -e ".[dev]"
```

## Configuration

The Sumo Logic MCP Server supports multiple configuration methods with comprehensive validation and clear error messages.

### Configuration Methods

The server supports configuration through multiple sources with the following precedence (highest to lowest):

1. **Command-line arguments** (highest precedence)
2. **Environment variables**
3. **Configuration file**
4. **Default values** (lowest precedence)

### Environment Variables

Configure the server using environment variables with the `SUMOLOGIC_` prefix:

| Variable | Required | Default | Description | Valid Values |
|----------|----------|---------|-------------|--------------|
| `SUMOLOGIC_ACCESS_ID` | ✅ | - | Your Sumo Logic Access ID | 14 alphanumeric characters |
| `SUMOLOGIC_ACCESS_KEY` | ✅ | - | Your Sumo Logic Access Key | At least 20 characters |
| `SUMOLOGIC_ENDPOINT` | ✅ | - | Sumo Logic API endpoint | Valid HTTPS URL ending in .sumologic.com |
| `SUMOLOGIC_TIMEOUT` | ❌ | 30 | Request timeout in seconds | 1-300 |
| `SUMOLOGIC_MAX_RETRIES` | ❌ | 3 | Maximum retry attempts | 0-10 |
| `SUMOLOGIC_RATE_LIMIT_DELAY` | ❌ | 1.0 | Delay between rate-limited requests | 0.1-60.0 |
| `SUMOLOGIC_LOG_LEVEL` | ❌ | INFO | Log level | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `SUMOLOGIC_LOG_FORMAT` | ❌ | json | Log format | json, text |
| `SUMOLOGIC_SERVER_NAME` | ❌ | sumologic-mcp-server | MCP server name | Any string |
| `SUMOLOGIC_SERVER_VERSION` | ❌ | 0.1.0 | MCP server version | Any string |

### Configuration File Support

Create a JSON configuration file for easier management:

**Minimal Configuration (config.json):**
```json
{
  "access_id": "your_access_id_here",
  "access_key": "your_access_key_here", 
  "endpoint": "https://api.sumologic.com"
}
```

**Full Configuration (config.json):**
```json
{
  "access_id": "your_access_id_here",
  "access_key": "your_access_key_here",
  "endpoint": "https://api.sumologic.com",
  "timeout": 30,
  "max_retries": 3,
  "rate_limit_delay": 1.0,
  "log_level": "INFO",
  "log_format": "json",
  "server_name": "sumologic-mcp-server",
  "server_version": "0.1.0"
}
```

Use the configuration file:
```bash
sumologic-mcp-server --config-file config.json
```

### Configuration Validation

The server includes comprehensive configuration validation with detailed error messages and recommendations.

**Validate Configuration:**
```bash
# Validate current environment configuration
sumologic-mcp-server --validate-config

# Validate specific configuration file
sumologic-mcp-server --config-file config.json --validate-config
```

**Example Validation Output:**
```
============================================================
SUMO LOGIC MCP SERVER - CONFIGURATION VALIDATION
============================================================

Configuration Sources:
  🌍 Environment variables: SUMOLOGIC_ACCESS_ID, SUMOLOGIC_ACCESS_KEY, SUMOLOGIC_ENDPOINT
  ⚙️  Using defaults for: timeout, max_retries, rate_limit_delay, log_level

Current Configuration:
  Access ID: ✓ (configured)
  Access Key: ✓ (configured)
  Endpoint: ✓ https://api.sumologic.com
  Timeout: 30s
  Max Retries: 3
  Rate Limit Delay: 1.0s
  Log Level: INFO
  Log Format: json

⚠️  CONFIGURATION WARNINGS:
  • timeout: Timeout of 5s is quite low and may cause request failures
    💡 Recommendation: Consider using a timeout of at least 10 seconds

✅ CONFIGURATION IS VALID - Server can start
============================================================
```

### Setup Instructions

1. **Get Sumo Logic Credentials:**
   - Log into your Sumo Logic account
   - Go to Administration > Security > Access Keys
   - Create a new Access Key or use existing credentials

2. **Choose Configuration Method:**
   
   **Option A: Environment Variables**
   ```bash
   export SUMOLOGIC_ACCESS_ID="your_access_id_here"
   export SUMOLOGIC_ACCESS_KEY="your_access_key_here"
   export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"
   ```

   **Option B: .env File**
   ```bash
   # Copy example file
   cp .env.example .env
   
   # Edit with your credentials
   nano .env
   ```

   **Option C: Configuration File**
   ```bash
   # Create config.json (see examples above)
   # Use with: sumologic-mcp-server --config-file config.json
   ```

3. **Validate Configuration:**
   ```bash
   sumologic-mcp-server --validate-config
   ```

4. **Start Server:**
   ```bash
   sumologic-mcp-server
   ```

### Configuration Examples

**Development Setup:**
```bash
export SUMOLOGIC_LOG_LEVEL=DEBUG
export SUMOLOGIC_LOG_FORMAT=text
export SUMOLOGIC_TIMEOUT=60
sumologic-mcp-server
```

**Production Setup:**
```json
{
  "access_id": "your_access_id",
  "access_key": "your_access_key", 
  "endpoint": "https://api.sumologic.com",
  "timeout": 45,
  "max_retries": 5,
  "rate_limit_delay": 1.5,
  "log_level": "WARNING",
  "log_format": "json"
}
```

**High-Volume Environment:**
```bash
export SUMOLOGIC_TIMEOUT=60
export SUMOLOGIC_MAX_RETRIES=5
export SUMOLOGIC_RATE_LIMIT_DELAY=0.5
export SUMOLOGIC_LOG_LEVEL=WARNING
```

### Configuration Troubleshooting

**Common Configuration Errors:**

1. **Missing Required Credentials:**
   ```
   ❌ access_id: Sumo Logic Access ID is required. Set SUMOLOGIC_ACCESS_ID environment variable.
   ```
   **Solution:** Set the required environment variables or add them to your config file.

2. **Invalid Endpoint Format:**
   ```
   ❌ endpoint: Endpoint must be a valid Sumo Logic domain
   ```
   **Solution:** Use a valid Sumo Logic endpoint (e.g., `https://api.sumologic.com`).

3. **Invalid Access ID Format:**
   ```
   ❌ access_id: Access ID must be 14 alphanumeric characters
   ```
   **Solution:** Verify your Access ID is exactly 14 characters.

4. **Configuration File Issues:**
   ```
   ❌ Configuration file error: Invalid JSON in configuration file
   ```
   **Solution:** Validate your JSON syntax using a JSON validator.

For detailed configuration documentation, see [docs/configuration.md](docs/configuration.md).

## Usage

### Starting the Server

**Basic Usage:**
```bash
sumologic-mcp-server
```

**With Custom Log Level:**
```bash
SUMOLOGIC_LOG_LEVEL=DEBUG sumologic-mcp-server
```

**With Text Logging:**
```bash
sumologic-mcp-server --log-format text
```

**Validate Configuration Only:**
```bash
sumologic-mcp-server --validate-config
```

### Command Line Options

```bash
sumologic-mcp-server --help
```

Available options:
- `--config-file PATH`: Path to configuration file (optional)
- `--validate-config`: Validate configuration and exit
- `--log-level LEVEL`: Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `--log-format FORMAT`: Override log format (json, text)
- `--version`: Show version information

### Running as Python Module

```bash
python -m sumologic_mcp
```

### MCP Client Integration

Configure your MCP client to connect to this server. Example configuration for various clients:

**Claude Desktop (config.json):**
```json
{
  "mcpServers": {
    "sumologic": {
      "command": "sumologic-mcp-server",
      "env": {
        "SUMOLOGIC_ACCESS_ID": "your_access_id",
        "SUMOLOGIC_ACCESS_KEY": "your_access_key",
        "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com"
      }
    }
  }
}
```

## Available Tools

### Search Tools
- `search_logs`: Execute log search queries
- `get_search_job_status`: Check search job status
- `get_search_results`: Retrieve search results with pagination

### Dashboard Tools
- `list_dashboards`: List all dashboards
- `get_dashboard`: Get specific dashboard details
- `create_dashboard`: Create new dashboard
- `update_dashboard`: Update existing dashboard
- `delete_dashboard`: Delete dashboard

### Metrics Tools
- `query_metrics`: Execute metrics queries
- `list_metric_sources`: List available metric sources

### Collector Tools
- `list_collectors`: List all collectors
- `get_collector`: Get collector details
- `create_collector`: Create new collector
- `update_collector`: Update collector configuration
- `delete_collector`: Delete collector
- `list_sources`: List sources in collector
- `create_source`: Create new source

## Development

### Setup Development Environment

1. **Clone and Install:**
   ```bash
   git clone https://github.com/sumologic/sumologic-mcp-python.git
   cd sumologic-mcp-python
   pip install -e ".[dev]"
   ```

2. **Install Pre-commit Hooks:**
   ```bash
   pre-commit install
   ```

### Development Commands

**Run Tests:**
```bash
# All tests
pytest

# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# With coverage
pytest --cov=sumologic_mcp --cov-report=html
```

**Code Formatting:**
```bash
# Format code
black sumologic_mcp/ tests/
isort sumologic_mcp/ tests/

# Check formatting
black --check sumologic_mcp/ tests/
isort --check-only sumologic_mcp/ tests/
```

**Type Checking:**
```bash
mypy sumologic_mcp/
```

**Linting:**
```bash
flake8 sumologic_mcp/ tests/
```

**Run All Checks:**
```bash
pre-commit run --all-files
```

### Project Structure

```
sumologic-mcp-python/
├── sumologic_mcp/           # Main package
│   ├── __init__.py
│   ├── main.py             # Entry point
│   ├── server.py           # MCP server implementation
│   ├── config.py           # Configuration management
│   ├── auth.py             # Authentication
│   ├── api_client.py       # Sumo Logic API client
│   ├── error_handler.py    # Error handling
│   ├── exceptions/         # Custom exceptions
│   ├── models/             # Data models
│   └── tools/              # MCP tool implementations
├── tests/                  # Test suite
├── .env.example           # Example environment file
├── pyproject.toml         # Project configuration
├── README.md              # This file
└── LICENSE                # License file
```

## Troubleshooting

### Common Issues

**Authentication Errors:**
- Verify your Access ID and Access Key are correct
- Ensure your endpoint URL is correct for your Sumo Logic deployment
- Check that your credentials have necessary permissions

**Connection Issues:**
- Verify network connectivity to Sumo Logic endpoints
- Check firewall settings
- Ensure proper SSL/TLS configuration

**Rate Limiting:**
- The server automatically handles rate limiting with exponential backoff
- Adjust `SUMOLOGIC_RATE_LIMIT_DELAY` if needed
- Monitor logs for rate limit warnings

### Debug Mode

Enable debug logging for detailed troubleshooting:
```bash
SUMOLOGIC_LOG_LEVEL=DEBUG sumologic-mcp-server --log-format text
```

### Getting Help

1. Check the [Issues](https://github.com/sumologic/sumologic-mcp-python/issues) page
2. Review Sumo Logic API documentation
3. Enable debug logging for detailed error information

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass and code is formatted
6. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built on the [Model Context Protocol](https://modelcontextprotocol.io/) specification
- Integrates with [Sumo Logic](https://www.sumologic.com/) APIs
- Inspired by the TypeScript implementation at [mcp-sumologic](https://github.com/samwang0723/mcp-sumologic)
