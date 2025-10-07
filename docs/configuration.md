# Sumo Logic MCP Server Configuration Guide

This guide covers all configuration options for the Sumo Logic MCP Server, including environment variables, configuration files, and validation.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration Methods](#configuration-methods)
- [Configuration Options](#configuration-options)
- [Validation](#validation)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Minimum Required Configuration

Set these three environment variables to get started:

```bash
export SUMOLOGIC_ACCESS_ID="your_access_id_here"
export SUMOLOGIC_ACCESS_KEY="your_access_key_here"
export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"
```

Then start the server:

```bash
python -m sumologic_mcp
```

### Validate Your Configuration

Before starting the server, validate your configuration:

```bash
python -m sumologic_mcp --validate-config
```

## Configuration Methods

The server supports multiple configuration methods with the following precedence (highest to lowest):

1. **Command-line arguments** (highest precedence)
2. **Environment variables**
3. **Configuration file**
4. **Default values** (lowest precedence)

### 1. Environment Variables

Set environment variables with the `SUMOLOGIC_` prefix:

```bash
# Required
export SUMOLOGIC_ACCESS_ID="your_access_id"
export SUMOLOGIC_ACCESS_KEY="your_access_key"
export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"

# Optional
export SUMOLOGIC_TIMEOUT=30
export SUMOLOGIC_MAX_RETRIES=3
export SUMOLOGIC_RATE_LIMIT_DELAY=1.0
export SUMOLOGIC_LOG_LEVEL=INFO
export SUMOLOGIC_LOG_FORMAT=json
export SUMOLOGIC_SERVER_NAME=sumologic-mcp-server
export SUMOLOGIC_SERVER_VERSION=0.1.0
```

### 2. Configuration File

Create a JSON configuration file:

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
  "server_name": "sumologic-mcp-server",
  "server_version": "0.1.0"
}
```

Use the configuration file:

```bash
python -m sumologic_mcp --config-file config.json
```

### 3. Command-line Arguments

Override specific settings:

```bash
python -m sumologic_mcp --log-level DEBUG --log-format text
```

## Configuration Options

### Required Options

| Option | Environment Variable | Description | Example |
|--------|---------------------|-------------|---------|
| `access_id` | `SUMOLOGIC_ACCESS_ID` | Sumo Logic Access ID | `suABCDEF123456789` |
| `access_key` | `SUMOLOGIC_ACCESS_KEY` | Sumo Logic Access Key | `abcdef1234567890abcdef1234567890` |
| `endpoint` | `SUMOLOGIC_ENDPOINT` | Sumo Logic API endpoint | `https://api.sumologic.com` |

### Optional Options

| Option | Environment Variable | Default | Description | Valid Values |
|--------|---------------------|---------|-------------|--------------|
| `timeout` | `SUMOLOGIC_TIMEOUT` | `30` | Request timeout in seconds | `1-300` |
| `max_retries` | `SUMOLOGIC_MAX_RETRIES` | `3` | Maximum retry attempts | `0-10` |
| `rate_limit_delay` | `SUMOLOGIC_RATE_LIMIT_DELAY` | `1.0` | Delay between rate-limited requests | `0.1-60.0` |
| `log_level` | `SUMOLOGIC_LOG_LEVEL` | `INFO` | Logging level | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `log_format` | `SUMOLOGIC_LOG_FORMAT` | `json` | Log output format | `json`, `text` |
| `server_name` | `SUMOLOGIC_SERVER_NAME` | `sumologic-mcp-server` | MCP server name | Any string |
| `server_version` | `SUMOLOGIC_SERVER_VERSION` | `0.1.0` | MCP server version | Any string |

### Configuration Validation Rules

#### Access ID
- Must be exactly 14 alphanumeric characters
- Example: `suABCDEF123456`

#### Access Key
- Must be at least 20 characters long
- Should be kept secure and never logged

#### Endpoint
- Must be a valid HTTPS URL
- Must end with `.sumologic.com`
- Common endpoints:
  - US1: `https://api.sumologic.com`
  - US2: `https://api.us2.sumologic.com`
  - EU: `https://api.eu.sumologic.com`
  - AU: `https://api.au.sumologic.com`

#### Timeout
- Range: 1-300 seconds
- Recommended: 30-120 seconds
- Lower values may cause timeouts for large queries
- Higher values may cause client timeouts

#### Max Retries
- Range: 0-10
- Recommended: 3-5
- Higher values increase reliability but may slow down error responses

#### Rate Limit Delay
- Range: 0.1-60.0 seconds
- Recommended: 0.5-2.0 seconds
- Lower values may trigger rate limiting
- Higher values reduce throughput

## Validation

### Automatic Validation

The server automatically validates configuration on startup and provides detailed error messages for invalid settings.

### Manual Validation

Validate configuration without starting the server:

```bash
python -m sumologic_mcp --validate-config
```

### Validation Output

The validation output includes:

- **Configuration Sources**: Shows which values came from environment variables, config files, or defaults
- **Current Configuration**: Displays all configuration values
- **Errors**: Lists any validation errors that prevent startup
- **Warnings**: Shows potential issues with current settings
- **Recommendations**: Suggests optimal configuration values

Example validation output:

```
============================================================
SUMO LOGIC MCP SERVER - CONFIGURATION VALIDATION
============================================================

Configuration Sources:
  🌍 Environment variables: SUMOLOGIC_ACCESS_ID, SUMOLOGIC_ACCESS_KEY, SUMOLOGIC_ENDPOINT
  ⚙️  Using defaults for: timeout, max_retries, rate_limit_delay, log_level, log_format

Current Configuration:
  Access ID: ✓ (configured)
  Access Key: ✓ (configured)
  Endpoint: ✓ https://api.sumologic.com
  Timeout: 30s
  Max Retries: 3
  Rate Limit Delay: 1.0s
  Log Level: INFO
  Log Format: json
  Server Name: sumologic-mcp-server
  Server Version: 0.1.0

✅ CONFIGURATION IS VALID - Server can start
============================================================
```

## Examples

### Example 1: Basic Setup with Environment Variables

```bash
# Set required credentials
export SUMOLOGIC_ACCESS_ID="suABCDEF123456"
export SUMOLOGIC_ACCESS_KEY="your_secret_access_key_here"
export SUMOLOGIC_ENDPOINT="https://api.sumologic.com"

# Start server
python -m sumologic_mcp
```

### Example 2: Development Setup with Debug Logging

```bash
# Use text logging for better readability during development
export SUMOLOGIC_LOG_LEVEL="DEBUG"
export SUMOLOGIC_LOG_FORMAT="text"
export SUMOLOGIC_TIMEOUT="60"

python -m sumologic_mcp
```

### Example 3: Production Setup with Configuration File

Create `production-config.json`:

```json
{
  "access_id": "suABCDEF123456",
  "access_key": "your_secret_access_key_here",
  "endpoint": "https://api.sumologic.com",
  "timeout": 45,
  "max_retries": 5,
  "rate_limit_delay": 1.5,
  "log_level": "WARNING",
  "log_format": "json",
  "server_name": "sumologic-mcp-prod",
  "server_version": "1.0.0"
}
```

Start with configuration file:

```bash
python -m sumologic_mcp --config-file production-config.json
```

### Example 4: Override Specific Settings

```bash
# Use config file but override log level
python -m sumologic_mcp --config-file config.json --log-level DEBUG
```

### Example 5: Using .env File

Create `.env` file in your project directory:

```bash
# Sumo Logic MCP Server Configuration
SUMOLOGIC_ACCESS_ID=suABCDEF123456
SUMOLOGIC_ACCESS_KEY=your_secret_access_key_here
SUMOLOGIC_ENDPOINT=https://api.sumologic.com
SUMOLOGIC_LOG_LEVEL=INFO
SUMOLOGIC_LOG_FORMAT=json
```

The server will automatically load the `.env` file if present.

## Troubleshooting

### Common Configuration Errors

#### 1. Missing Required Credentials

**Error**: `access_id: Sumo Logic Access ID is required`

**Solution**: Set the `SUMOLOGIC_ACCESS_ID` environment variable or add it to your config file.

#### 2. Invalid Endpoint Format

**Error**: `endpoint: Endpoint must be a valid Sumo Logic domain`

**Solution**: Ensure your endpoint starts with `https://` and ends with `.sumologic.com`.

#### 3. Invalid Access ID Format

**Error**: `access_id: Access ID must be 14 alphanumeric characters`

**Solution**: Check that your Access ID is exactly 14 characters and contains only letters and numbers.

#### 4. Configuration File Not Found

**Error**: `Configuration file not found: config.json`

**Solution**: 
- Check the file path is correct
- Create the configuration file
- Remove the `--config-file` option to use environment variables only

#### 5. Invalid JSON in Configuration File

**Error**: `Invalid JSON in configuration file: Expecting ',' delimiter`

**Solution**: Validate your JSON syntax using a JSON validator or linter.

### Performance Tuning

#### For High-Volume Environments

```json
{
  "timeout": 60,
  "max_retries": 5,
  "rate_limit_delay": 0.5,
  "log_level": "WARNING"
}
```

#### For Development/Testing

```json
{
  "timeout": 30,
  "max_retries": 2,
  "rate_limit_delay": 0.1,
  "log_level": "DEBUG",
  "log_format": "text"
}
```

### Getting Help

1. **Validate Configuration**: `python -m sumologic_mcp --validate-config`
2. **View Help**: `python -m sumologic_mcp --help`
3. **Check Logs**: Enable DEBUG logging to see detailed error information
4. **Test Connection**: Use the validation command to test your Sumo Logic credentials

### Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** in production
3. **Restrict file permissions** on configuration files containing credentials
4. **Rotate access keys** regularly
5. **Use separate credentials** for different environments (dev/staging/prod)

### Environment-Specific Configurations

#### Development
```bash
export SUMOLOGIC_LOG_LEVEL=DEBUG
export SUMOLOGIC_LOG_FORMAT=text
export SUMOLOGIC_TIMEOUT=60
```

#### Staging
```bash
export SUMOLOGIC_LOG_LEVEL=INFO
export SUMOLOGIC_LOG_FORMAT=json
export SUMOLOGIC_MAX_RETRIES=5
```

#### Production
```bash
export SUMOLOGIC_LOG_LEVEL=WARNING
export SUMOLOGIC_LOG_FORMAT=json
export SUMOLOGIC_TIMEOUT=45
export SUMOLOGIC_MAX_RETRIES=5
export SUMOLOGIC_RATE_LIMIT_DELAY=1.5
```