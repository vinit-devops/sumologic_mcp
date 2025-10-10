"""Main MCP server implementation for Sumo Logic.

Note: This implementation uses a workaround for MCP Python SDK bug #987
where CallToolResult objects are incorrectly serialized. We return plain
dictionaries instead of CallToolResult objects to avoid validation errors.
See: https://github.com/modelcontextprotocol/python-sdk/issues/987
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from .config import SumoLogicConfig
from .auth import SumoLogicAuth
from .api_client import SumoLogicAPIClient
from .tools.search_tools import SearchTools
from .tools.dashboard_tools import DashboardTools
from .tools.metrics_tools import MetricsTools
from .tools.collector_tools import CollectorTools
from .tools.monitor_tools import MonitorTools
from .exceptions import SumoLogicError, ValidationError, APIError
from .error_handler import ErrorHandler
from .monitoring import MonitoringManager

logger = structlog.get_logger(__name__)


class SumoLogicMCPServer:
    """Main MCP server class for Sumo Logic integration."""
    
    def __init__(self, config: SumoLogicConfig):
        """Initialize the MCP server with configuration.
        
        Args:
            config: SumoLogicConfig instance with server configuration
        """
        self.config = config
        self.logger = logger.bind(server_name=config.server_name)
        
        # Initialize MCP server
        self.mcp_server = Server(config.server_name)
        
        # Initialize components
        self.auth: Optional[SumoLogicAuth] = None
        self.api_client: Optional[SumoLogicAPIClient] = None
        self.search_tools: Optional[SearchTools] = None
        self.dashboard_tools: Optional[DashboardTools] = None
        self.metrics_tools: Optional[MetricsTools] = None
        self.collector_tools: Optional[CollectorTools] = None
        self.monitor_tools: Optional[MonitorTools] = None
        
        # Tool registry
        self.tool_handlers: Dict[str, Callable] = {}
        
        # Initialize error handler and monitoring
        self.error_handler = ErrorHandler(config.server_name)
        self.monitoring_manager = MonitoringManager()
        
        # Configure logging
        self._configure_logging()
        
    def _configure_logging(self) -> None:
        """Configure structured logging for the server."""
        # Use centralized logging configuration
        ErrorHandler.configure_logging(
            log_level=self.config.log_level,
            log_format=self.config.log_format
        )
        
    async def start(self) -> None:
        """Initialize and start the MCP server."""
        try:
            self.logger.info(
                "Starting Sumo Logic MCP server",
                version=self.config.server_version,
                endpoint=self.config.endpoint,
                log_level=self.config.log_level
            )
            
            # Initialize authentication (defer actual authentication until first use)
            self.auth = SumoLogicAuth(self.config)
            # Note: We don't authenticate here to allow the server to start even with invalid credentials
            # Authentication will happen on first API call
            
            # Initialize API client
            self.api_client = SumoLogicAPIClient(self.config, self.auth)
            
            # Initialize tool handlers
            self.search_tools = SearchTools(self.api_client)
            self.dashboard_tools = DashboardTools(self.api_client)
            self.metrics_tools = MetricsTools(self.api_client)
            self.collector_tools = CollectorTools(self.api_client)
            self.monitor_tools = MonitorTools(self.api_client)
            
            # Start monitoring
            await self.monitoring_manager.start()
            
            # Register connection monitoring for Sumo Logic API
            await self.monitoring_manager.connection_monitor.register_connection(
                name="sumologic_api",
                endpoint=self.config.endpoint,
                check_func=self._check_api_connection
            )
            
            # Register health checks
            await self._register_health_checks()
            
            # Register all tools
            self.register_tools()
            
            # Register health check tool
            self._register_health_check_tool()
            
            self.logger.info(
                "Sumo Logic MCP server started successfully",
                tools_registered=len(self.tool_handlers)
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to start MCP server",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
        
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Route tool calls to appropriate handlers.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Dict with tool execution result (workaround for MCP SDK bug)
        """
        start_time = asyncio.get_event_loop().time()
        
        # Log incoming request
        self.error_handler.log_request(tool_name, arguments)
        
        try:
            # Check if tool exists
            if tool_name not in self.tool_handlers:
                error_msg = f"Unknown tool: {tool_name}"
                self.logger.error(error_msg, available_tools=list(self.tool_handlers.keys()))
                # Return dict directly to avoid MCP SDK serialization bug
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {error_msg}. Available tools: {', '.join(self.tool_handlers.keys())}",
                            "annotations": None
                        }
                    ],
                    "isError": True
                }
            
            # Get tool handler
            handler = self.tool_handlers[tool_name]
            
            # Execute tool
            result = await handler(**arguments)
            
            # Calculate execution time
            execution_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            # Log successful response
            response_text = self._format_tool_result(result)
            self.error_handler.log_response(
                tool_name, 
                success=True, 
                execution_time_ms=execution_time,
                response_size=len(response_text)
            )
            
            # Return dict directly to avoid MCP SDK serialization bug
            return {
                "content": [
                    {
                        "type": "text",
                        "text": response_text,
                        "annotations": None
                    }
                ],
                "isError": False
            }
            
        except Exception as e:
            # Calculate execution time for error case
            execution_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            # Log error response
            self.error_handler.log_response(
                tool_name, 
                success=False, 
                execution_time_ms=execution_time
            )
            
            # Use centralized error handler
            return self.error_handler.handle_tool_error(
                error=e,
                tool_name=tool_name,
                arguments=arguments,
                execution_time_ms=execution_time
            )
        
    def register_tools(self) -> None:
        """Register all available Sumo Logic tools."""
        self.logger.info("Registering MCP tools")
        
        try:
            # Collect all tool definitions
            all_tools = []
            
            # Get search tools
            search_tool_defs = self.search_tools.get_tool_definitions()
            all_tools.extend(search_tool_defs)
            
            # Get dashboard tools  
            dashboard_tool_defs = self.dashboard_tools.get_tool_definitions()
            all_tools.extend(dashboard_tool_defs)
            
            # Get metrics tools
            metrics_tool_defs = self.metrics_tools.get_tool_definitions()
            all_tools.extend(metrics_tool_defs)
            
            # Get collector tools
            collector_tool_defs = self.collector_tools.get_tool_definitions()
            all_tools.extend(collector_tool_defs)
            
            # Get monitor tools
            monitor_tool_defs = self.monitor_tools.get_tool_definitions()
            all_tools.extend(monitor_tool_defs)
            
            # Add health check tool
            health_check_tool = {
                "name": "health_check",
                "description": "Get comprehensive health status of the Sumo Logic MCP server",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_metrics": {
                            "type": "boolean",
                            "description": "Include detailed metrics in the response",
                            "default": False
                        },
                        "include_connections": {
                            "type": "boolean", 
                            "description": "Include connection status in the response",
                            "default": True
                        }
                    },
                    "additionalProperties": False
                }
            }
            all_tools.append(health_check_tool)
            
            # Register tool handlers
            for tool_def in all_tools:
                tool_name = tool_def["name"]
                
                # Find the appropriate tool class and register handler
                if tool_name in [t["name"] for t in search_tool_defs]:
                    handler = getattr(self.search_tools, tool_name)
                elif tool_name in [t["name"] for t in dashboard_tool_defs]:
                    handler = getattr(self.dashboard_tools, tool_name)
                elif tool_name in [t["name"] for t in metrics_tool_defs]:
                    handler = getattr(self.metrics_tools, tool_name)
                elif tool_name in [t["name"] for t in collector_tool_defs]:
                    handler = getattr(self.collector_tools, tool_name)
                elif tool_name in [t["name"] for t in monitor_tool_defs]:
                    handler = getattr(self.monitor_tools, tool_name)
                else:
                    continue
                    
                self.tool_handlers[tool_name] = handler
            
            # Register the list_tools handler with MCP server
            @self.mcp_server.list_tools()
            async def list_tools_handler():
                from mcp.types import Tool
                return [
                    Tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        inputSchema=tool_def["inputSchema"]
                    )
                    for tool_def in all_tools
                ]
            
            self.logger.info(
                "All MCP tools registered successfully",
                total_tools=len(all_tools),
                search_tools=len(search_tool_defs),
                dashboard_tools=len(dashboard_tool_defs),
                metrics_tools=len(metrics_tool_defs),
                collector_tools=len(collector_tool_defs),
                monitor_tools=len(monitor_tool_defs)
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to register tools",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
    

    
    def _format_tool_result(self, result: Any) -> str:
        """Format tool execution result for MCP response.
        
        Args:
            result: Tool execution result
            
        Returns:
            Formatted string representation of the result
        """
        try:
            import json
            return json.dumps(result, indent=2, default=str)
        except Exception:
            return str(result)
    
    async def run_stdio(self) -> None:
        """Run the MCP server using stdio transport."""
        self.logger.info("Starting MCP server with stdio transport")
        
        # Set up tool call handler
        @self.mcp_server.call_tool()
        async def handle_call_tool(name: str, arguments: dict):
            # Workaround for MCP SDK bug: return dict instead of CallToolResult
            # See: https://github.com/modelcontextprotocol/python-sdk/issues/987
            try:
                result = await self.handle_tool_call(name, arguments)
                # Result is already a dict, return it directly
                return result
            except Exception as e:
                # If there's an issue with our response construction, create a simple fallback
                self.logger.error(f"Error in tool call handler: {e}")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Internal error: {str(e)}",
                            "annotations": None
                        }
                    ],
                    "isError": True
                }
        
        # Run server with stdio
        async with stdio_server() as (read_stream, write_stream):
            await self.mcp_server.run(
                read_stream,
                write_stream,
                self.mcp_server.create_initialization_options()
            )
    
    async def _check_api_connection(self) -> None:
        """Check connection to Sumo Logic API."""
        if not self.api_client:
            raise SumoLogicError("API client not initialized")
        
        # Try to make a simple API call to check connectivity
        try:
            # Use a lightweight endpoint to check connectivity
            await self.api_client._make_request(
                method="GET",
                endpoint="/api/v1/collectors",
                params={"limit": 1},
                operation_type="health_check"
            )
        except Exception as e:
            raise SumoLogicError(f"API connection check failed: {e}") from e
    
    async def _register_health_checks(self) -> None:
        """Register health checks for the server."""
        # API client health check
        await self.monitoring_manager.health_checker.register_health_check(
            "api_client",
            self._check_api_client_health,
            "Check if API client is healthy and responsive"
        )
        
        # Authentication health check
        await self.monitoring_manager.health_checker.register_health_check(
            "authentication",
            self._check_authentication_health,
            "Check if authentication is valid and working"
        )
        
        # Tool handlers health check
        await self.monitoring_manager.health_checker.register_health_check(
            "tool_handlers",
            self._check_tool_handlers_health,
            "Check if all tool handlers are properly initialized"
        )
    
    async def _check_api_client_health(self) -> None:
        """Health check for API client."""
        if not self.api_client:
            raise SumoLogicError("API client not initialized")
        
        # Get API client health status
        health_status = await self.api_client.get_health_status()
        
        # Check if resilience components are healthy
        if health_status["resilience"]["health"] == "unhealthy":
            raise SumoLogicError("API client resilience components are unhealthy")
    
    async def _check_authentication_health(self) -> None:
        """Health check for authentication."""
        if not self.auth:
            raise SumoLogicError("Authentication not initialized")
        
        # Check if authentication is valid (but don't fail if not authenticated yet)
        try:
            await self.auth.get_auth_headers()
        except Exception as e:
            # For MCP servers, we allow starting without valid credentials
            # Authentication will be attempted on first API call
            self.logger.warning(f"Authentication not yet validated: {e}")
            # Don't raise an error here - just log the warning
    
    async def _check_tool_handlers_health(self) -> None:
        """Health check for tool handlers."""
        required_tools = [
            self.search_tools,
            self.dashboard_tools,
            self.metrics_tools,
            self.collector_tools,
            self.monitor_tools
        ]
        
        for tool in required_tools:
            if tool is None:
                raise SumoLogicError(f"Tool handler {type(tool).__name__} not initialized")
        
        if not self.tool_handlers:
            raise SumoLogicError("No tool handlers registered")
    
    def _register_health_check_tool(self) -> None:
        """Register the health check tool."""
        # The health check tool is now registered in the main register_tools method
        # Just register the handler here
        self.tool_handlers["health_check"] = self._handle_health_check
    
    async def _handle_health_check(
        self,
        include_metrics: bool = False,
        include_connections: bool = True
    ) -> Dict[str, Any]:
        """Handle health check tool call.
        
        Args:
            include_metrics: Whether to include detailed metrics
            include_connections: Whether to include connection status
            
        Returns:
            Comprehensive health status
        """
        try:
            # Get comprehensive monitoring status
            status = await self.monitoring_manager.get_comprehensive_status()
            
            # Add server-specific information
            status["server"] = {
                "name": self.config.server_name,
                "version": self.config.server_version,
                "endpoint": self.config.endpoint,
                "tools_registered": len(self.tool_handlers),
                "uptime_info": "Server is running"  # Could be enhanced with actual uptime
            }
            
            # Optionally exclude metrics for lighter response
            if not include_metrics:
                status.pop("metrics", None)
            
            # Optionally exclude connections
            if not include_connections:
                status.pop("connections", None)
            
            return status
            
        except Exception as e:
            self.logger.error(
                "Health check failed",
                error=str(e),
                error_type=type(e).__name__
            )
            
            return {
                "timestamp": "error",
                "health": {
                    "status": "unhealthy",
                    "message": f"Health check failed: {str(e)}",
                    "checks": {}
                },
                "server": {
                    "name": self.config.server_name,
                    "version": self.config.server_version,
                    "error": str(e)
                }
            }

    async def shutdown(self) -> None:
        """Shutdown the MCP server and clean up resources."""
        self.logger.info("Shutting down Sumo Logic MCP server")
        
        try:
            # Stop monitoring
            if self.monitoring_manager:
                await self.monitoring_manager.stop()
            
            # Close API client
            if self.api_client:
                await self.api_client.close()
            
            # Logout from authentication
            if self.auth:
                await self.auth.logout()
            
            self.logger.info("MCP server shutdown completed")
            
        except Exception as e:
            self.logger.error(
                "Error during server shutdown",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.shutdown()