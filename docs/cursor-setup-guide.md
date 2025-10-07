# Using Sumo Logic MCP Server in Cursor

This guide shows you how to set up and use the Sumo Logic MCP server in Cursor IDE.

## Prerequisites

1. **Sumo Logic Account**: You need a Sumo Logic account with API access
2. **Python 3.8+**: Make sure Python is installed on your system
3. **Cursor IDE**: Latest version of Cursor IDE

## Step 1: Install the MCP Server

### Option A: Install from Source (Recommended for Development)

```bash
# Clone the repository
git clone https://github.com/your-repo/sumologic-mcp-python.git
cd sumologic-mcp-python

# Install the package
pip install -e .
```

### Option B: Install from PyPI (When Available)

```bash
pip install sumologic-mcp-python
```

## Step 2: Get Your Sumo Logic Credentials

1. Log into your Sumo Logic account
2. Go to **Administration** > **Security** > **Access Keys**
3. Create a new Access Key or use existing credentials
4. Note down:
   - **Access ID** (14 alphanumeric characters)
   - **Access Key** (long string)
   - **Endpoint** (e.g., `https://api.sumologic.com` or your specific deployment URL)

## Step 3: Configure Cursor to Use the MCP Server

### Method 1: Using Cursor's MCP Settings (Recommended)

1. Open Cursor IDE
2. Go to **Settings** (Cmd/Ctrl + ,)
3. Search for "MCP" or look for "Model Context Protocol" settings
4. Add a new MCP server with these settings:

```json
{
  "name": "sumologic",
  "command": "sumologic-mcp-server",
  "env": {
    "SUMOLOGIC_ACCESS_ID": "your_access_id_here",
    "SUMOLOGIC_ACCESS_KEY": "your_access_key_here",
    "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com"
  }
}
```

### Method 2: Using Configuration File

If Cursor uses a configuration file (similar to Claude Desktop), create or edit the MCP configuration:

**Location**: Usually in your user config directory
**File**: `mcp_servers.json` or similar

```json
{
  "mcpServers": {
    "sumologic": {
      "command": "sumologic-mcp-server",
      "env": {
        "SUMOLOGIC_ACCESS_ID": "your_access_id_here",
        "SUMOLOGIC_ACCESS_KEY": "your_access_key_here",
        "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com",
        "SUMOLOGIC_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Method 3: Using Python Module Command

If the direct command doesn't work, try using the Python module:

```json
{
  "name": "sumologic",
  "command": "python",
  "args": ["-m", "sumologic_mcp"],
  "env": {
    "SUMOLOGIC_ACCESS_ID": "your_access_id_here",
    "SUMOLOGIC_ACCESS_KEY": "your_access_key_here",
    "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com"
  }
}
```

## Step 4: Test the Connection

1. Restart Cursor IDE
2. Open a new chat or conversation
3. Try using one of the Sumo Logic tools:

```
Can you search for error logs in the last hour using the search_logs tool?
```

Or test with a specific query:

```
Use the execute_query tool to search for:
- Query: error OR exception
- Time range: last 1 hour
- Limit: 50 results
```

## Available Tools in Cursor

Once configured, you'll have access to these Sumo Logic tools:

### 🔍 Search & Analytics Tools
- **`search_logs`**: Execute log search queries
- **`execute_query`**: Reference-compatible query execution
- **`get_search_job_status`**: Check search job status
- **`get_search_results`**: Retrieve paginated results
- **`validate_query_syntax`**: Validate queries without execution
- **`list_source_categories`**: Discover available source categories
- **`get_sample_data`**: Get sample data from source categories

### 📊 Dashboard Tools
- **`list_dashboards`**: List all dashboards
- **`get_dashboard`**: Get dashboard details
- **`create_dashboard`**: Create new dashboards
- **`update_dashboard`**: Update existing dashboards
- **`delete_dashboard`**: Delete dashboards

### 📈 Metrics Tools
- **`query_metrics`**: Execute metrics queries
- **`list_metric_sources`**: List available metrics
- **`list_metrics`**: Reference-compatible metrics listing
- **`get_metric_metadata`**: Get detailed metric information

### 🔧 Collector Tools
- **`list_collectors`**: List all collectors
- **`get_collector`**: Get collector details
- **`create_collector`**: Create new collectors
- **`update_collector`**: Update collector configuration
- **`delete_collector`**: Delete collectors
- **`list_sources`**: List sources in collectors
- **`create_source`**: Create new sources

### 🖥️ VMware Monitoring
- **`explore_vmware_metrics`**: Comprehensive VMware metrics exploration

### 🏥 Health & Monitoring
- **`health_check`**: Get server health status

## Example Usage in Cursor

Here are some example prompts you can use in Cursor:

### Basic Log Search
```
Search for application errors in the last 2 hours using search_logs with:
- Query: _sourceCategory="app/logs" AND level=ERROR
- Time: last 2 hours
- Limit: 100
```

### VMware Monitoring
```
Use explore_vmware_metrics to analyze VMware performance metrics from the "otel/vmware" source category
```

### Dashboard Management
```
List all dashboards and show me the details of any dashboard related to "performance" or "monitoring"
```

### Metrics Analysis
```
Query CPU metrics for the last hour using query_metrics:
- Query: cpu.usage.average
- Time range: -1h to now
- Max data points: 100
```

### Source Category Discovery
```
Use list_source_categories to find all available source categories that contain "app" or "service"
```

## Troubleshooting

### Common Issues

1. **Command Not Found**
   ```bash
   # Make sure the package is installed
   pip install -e .
   
   # Or use the Python module approach
   python -m sumologic_mcp --help
   ```

2. **Authentication Errors**
   - Double-check your Access ID and Access Key
   - Verify the endpoint URL is correct
   - Test credentials with the validation command:
   ```bash
   sumologic-mcp-server --validate-config
   ```

3. **Connection Issues**
   - Check your network connection
   - Verify firewall settings allow HTTPS connections
   - Try with debug logging:
   ```json
   {
     "env": {
       "SUMOLOGIC_LOG_LEVEL": "DEBUG",
       "SUMOLOGIC_LOG_FORMAT": "text"
     }
   }
   ```

4. **Tool Not Available**
   - Restart Cursor after configuration changes
   - Check the MCP server logs for errors
   - Verify the server is running with: `sumologic-mcp-server --validate-config`

### Debug Mode

Enable debug logging to troubleshoot issues:

```json
{
  "name": "sumologic",
  "command": "sumologic-mcp-server",
  "env": {
    "SUMOLOGIC_ACCESS_ID": "your_access_id",
    "SUMOLOGIC_ACCESS_KEY": "your_access_key",
    "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com",
    "SUMOLOGIC_LOG_LEVEL": "DEBUG",
    "SUMOLOGIC_LOG_FORMAT": "text"
  }
}
```

### Testing Configuration

Before using in Cursor, test your configuration:

```bash
# Test configuration
sumologic-mcp-server --validate-config

# Test with debug output
SUMOLOGIC_LOG_LEVEL=DEBUG sumologic-mcp-server --validate-config
```

## Advanced Configuration

### Custom Timeouts and Limits

```json
{
  "env": {
    "SUMOLOGIC_ACCESS_ID": "your_access_id",
    "SUMOLOGIC_ACCESS_KEY": "your_access_key",
    "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com",
    "SUMOLOGIC_TIMEOUT": "60",
    "SUMOLOGIC_MAX_RETRIES": "5",
    "QUERY_TIMEOUT": "300",
    "MAX_RESULTS": "1000",
    "DEFAULT_VMWARE_SOURCE": "otel/vmware"
  }
}
```

### Reference Implementation Compatibility

The server supports reference environment variables for easy migration:

```json
{
  "env": {
    "SUMO_ACCESS_ID": "your_access_id",
    "SUMO_ACCESS_KEY": "your_access_key",
    "SUMO_ENDPOINT": "https://api.sumologic.com",
    "QUERY_TIMEOUT": "300",
    "MAX_RESULTS": "1000"
  }
}
```

## Best Practices

1. **Use Environment Variables**: Store credentials in environment variables rather than config files
2. **Enable Logging**: Use INFO or DEBUG level for troubleshooting
3. **Set Appropriate Timeouts**: Adjust timeouts based on your query complexity
4. **Monitor Rate Limits**: The server handles rate limiting automatically
5. **Use Health Checks**: Regularly check server health with the health_check tool

## Getting Help

1. **Configuration Issues**: Use `sumologic-mcp-server --validate-config`
2. **Connection Problems**: Enable DEBUG logging
3. **Tool Errors**: Check the server logs and Cursor's MCP logs
4. **Performance Issues**: Adjust timeout and retry settings

## Next Steps

Once you have the MCP server working in Cursor:

1. **Explore Tools**: Try different tools to understand their capabilities
2. **Create Workflows**: Build common log analysis and monitoring workflows
3. **Dashboard Integration**: Use dashboard tools to manage your Sumo Logic dashboards
4. **VMware Monitoring**: If you use VMware, explore the specialized VMware tools
5. **Automation**: Create automated monitoring and alerting workflows

Happy monitoring with Sumo Logic and Cursor! 🚀