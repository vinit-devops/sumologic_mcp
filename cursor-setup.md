# 🎯 Cursor Setup Guide for Sumo Logic MCP Server

Your Sumo Logic MCP server is now **working perfectly**! Here's how to configure it in Cursor.

## ✅ Server Status
- **25 tools** successfully registered
- **All tool categories** working: Search, Dashboard, Metrics, Collector, Health
- **Reference compatibility** tools included (execute_query, list_metrics, etc.)
- **VMware monitoring** tools available
- **Graceful startup** without requiring valid credentials upfront

## 🔧 Cursor Configuration

### Step 1: Set Up Your Credentials

First, create your `.env` file with your actual Sumo Logic credentials:

```bash
# Copy the example file
cp .env.example .env

# Edit with your actual credentials
nano .env
```

Add your real credentials:
```bash
SUMOLOGIC_ACCESS_ID=your_actual_access_id_here
SUMOLOGIC_ACCESS_KEY=your_actual_access_key_here
SUMOLOGIC_ENDPOINT=https://api.sumologic.com
```

### Step 2: Configure Cursor

Add this configuration to Cursor. The exact location depends on your Cursor version:

#### Option A: Cursor Settings UI
1. Open Cursor
2. Go to Settings (Cmd/Ctrl + ,)
3. Search for "MCP" or "Model Context Protocol"
4. Add a new server:

```json
{
  "name": "sumologic",
  "command": "/Users/vinitkumar/mcpservers/sumologic-mcp-env/bin/sumologic-mcp-server",
  "env": {
    "SUMOLOGIC_ACCESS_ID": "your_access_id_here",
    "SUMOLOGIC_ACCESS_KEY": "your_access_key_here", 
    "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com",
    "SUMOLOGIC_LOG_LEVEL": "INFO"
  }
}
```

#### Option B: Configuration File
Create or edit the MCP configuration file:

**macOS**: `~/Library/Application Support/Cursor/mcp_servers.json`
**Linux**: `~/.config/cursor/mcp_servers.json`  
**Windows**: `%APPDATA%\Cursor\mcp_servers.json`

```json
{
  "mcpServers": {
    "sumologic": {
      "command": "/Users/vinitkumar/mcpservers/sumologic-mcp-env/bin/sumologic-mcp-server",
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

#### Option C: Using Python Module (Alternative)
If the direct command doesn't work:

```json
{
  "mcpServers": {
    "sumologic": {
      "command": "/Users/vinitkumar/mcpservers/sumologic-mcp-env/bin/python",
      "args": ["-m", "sumologic_mcp"],
      "cwd": "/Users/vinitkumar/mcpservers",
      "env": {
        "SUMOLOGIC_ACCESS_ID": "your_access_id_here",
        "SUMOLOGIC_ACCESS_KEY": "your_access_key_here",
        "SUMOLOGIC_ENDPOINT": "https://api.sumologic.com"
      }
    }
  }
}
```

### Step 3: Test the Configuration

1. **Restart Cursor** after making configuration changes
2. **Open a new chat** or conversation
3. **Test the connection**:

```
Can you use the health_check tool to verify the Sumo Logic MCP server is working?
```

## 🛠️ Available Tools (25 Total)

### 🔍 **Search & Analytics (8 tools)**
- `search_logs` - Execute log search queries
- `execute_query` - Reference-compatible query execution
- `get_search_job_status` - Check search job status  
- `get_search_results` - Retrieve paginated results
- `validate_query_syntax` - Validate queries without execution
- `list_source_categories` - Discover available source categories
- `get_sample_data` - Get sample data from source categories
- `explore_vmware_metrics` - VMware metrics exploration

### 📊 **Dashboard Management (5 tools)**
- `list_dashboards` - List all dashboards
- `get_dashboard` - Get dashboard details
- `create_dashboard` - Create new dashboards
- `update_dashboard` - Update existing dashboards
- `delete_dashboard` - Delete dashboards

### 📈 **Metrics & Monitoring (4 tools)**
- `query_metrics` - Execute metrics queries
- `list_metric_sources` - List available metrics
- `list_metrics` - Reference-compatible metrics listing
- `get_metric_metadata` - Get detailed metric information

### 🔧 **Infrastructure Management (7 tools)**
- `list_collectors` - List all collectors
- `get_collector` - Get collector details
- `create_collector` - Create new collectors
- `update_collector` - Update collector configuration
- `delete_collector` - Delete collectors
- `list_sources` - List sources in collectors
- `create_source` - Create new sources

### 🏥 **Health & Monitoring (1 tool)**
- `health_check` - Get server health status

## 🚀 Example Usage in Cursor

Once configured, try these prompts:

### Basic Log Search
```
Search for application errors in the last 2 hours using search_logs:
- Query: _sourceCategory="app/logs" AND level=ERROR
- Time: -2h to now
- Limit: 100
```

### Reference Compatibility
```
Use execute_query (reference compatibility) to search for:
- Query: error OR exception
- Time range: last 1 hour
- Limit: 50
```

### VMware Monitoring
```
Use explore_vmware_metrics to analyze VMware performance metrics from the "otel/vmware" source category
```

### Dashboard Management
```
List all dashboards and show me details of any dashboard related to "performance"
```

### Health Check
```
Run a health_check to verify the Sumo Logic MCP server status and include metrics
```

## 🔧 Troubleshooting

### If Tools Don't Appear in Cursor:

1. **Check the command path**:
   ```bash
   # Verify the command exists
   ls -la /Users/vinitkumar/mcpservers/sumologic-mcp-env/bin/sumologic-mcp-server
   
   # Test it manually
   source sumologic-mcp-env/bin/activate
   sumologic-mcp-server --help
   ```

2. **Check your credentials**:
   ```bash
   # Validate configuration
   source sumologic-mcp-env/bin/activate
   sumologic-mcp-server --validate-config
   ```

3. **Enable debug logging**:
   ```json
   {
     "env": {
       "SUMOLOGIC_LOG_LEVEL": "DEBUG",
       "SUMOLOGIC_LOG_FORMAT": "text"
     }
   }
   ```

4. **Try the Python module approach** (Option C above)

5. **Check Cursor's MCP logs** (if available in Cursor's developer tools)

### Common Issues:

- **"Command not found"**: Use the full path to the executable
- **"Authentication failed"**: Check your credentials with `--validate-config`
- **"Tools not loading"**: Restart Cursor and wait a moment for initialization
- **"Connection timeout"**: Check your network and firewall settings

## 🎯 Success Indicators

You'll know it's working when:
- ✅ Cursor shows "Sumo Logic" tools in the available tools list
- ✅ You can successfully run `health_check` 
- ✅ Search queries return results
- ✅ No authentication errors in logs

## 🔄 Quick Test Commands

```bash
# Test server manually
source sumologic-mcp-env/bin/activate
sumologic-mcp-server --validate-config

# Test with debug output  
SUMOLOGIC_LOG_LEVEL=DEBUG sumologic-mcp-server --validate-config
```

Your Sumo Logic MCP server is ready to use! 🚀