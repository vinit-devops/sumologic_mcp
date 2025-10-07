# Configuration Examples

This directory contains example configuration files for various deployment scenarios.

## MCP Client Configuration

### Claude Desktop
- `claude-desktop-config.json`: Configuration for Claude Desktop MCP client
- Place in your Claude Desktop configuration directory

### Generic MCP Client
- `mcp-client-config.json`: Generic MCP client configuration
- Adapt for your specific MCP client

## Deployment Examples

### Docker
- `docker-compose.yml`: Docker Compose configuration for containerized deployment
- Build and run: `docker-compose up --build`

### Systemd Service
- `systemd/sumologic-mcp.service`: Systemd service configuration for Linux systems
- Install: `sudo cp systemd/sumologic-mcp.service /etc/systemd/system/`
- Enable: `sudo systemctl enable sumologic-mcp.service`
- Start: `sudo systemctl start sumologic-mcp.service`

## Usage Notes

1. Replace placeholder values (like `your_access_id_here`) with your actual Sumo Logic credentials
2. Adjust paths and user accounts as needed for your environment
3. Ensure proper file permissions for security
4. Test configurations in development before production deployment