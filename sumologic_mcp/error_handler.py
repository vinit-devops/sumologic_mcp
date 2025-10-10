"""Centralized error handling and logging for Sumo Logic MCP server.

Note: This implementation uses a workaround for MCP Python SDK bug #987
where CallToolResult objects are incorrectly serialized. We return plain
dictionaries instead of CallToolResult objects to avoid validation errors.
See: https://github.com/modelcontextprotocol/python-sdk/issues/987
"""

import logging
import traceback
from typing import Dict, Any, Optional, Union
import structlog
# MCP types no longer needed due to workaround for SDK bug
# from mcp.types import CallToolResult, TextContent

from .exceptions import (
    SumoLogicError,
    AuthenticationError,
    APIError,
    RateLimitError,
    ValidationError,
    ConfigurationError,
    SearchError,
    TimeoutError
)

logger = structlog.get_logger(__name__)


class ErrorHandler:
    """Centralized error handling and logging for MCP operations."""
    
    def __init__(self, server_name: str = "sumologic-mcp-server"):
        """Initialize error handler.
        
        Args:
            server_name: Name of the MCP server for logging context
        """
        self.server_name = server_name
        self.logger = logger.bind(server_name=server_name)
    
    def handle_tool_error(
        self,
        error: Exception,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_time_ms: Optional[float] = None
    ) -> Dict[str, Any]:
        """Handle errors from tool execution and format MCP response.
        
        Args:
            error: Exception that occurred during tool execution
            tool_name: Name of the tool that failed
            arguments: Arguments passed to the tool
            execution_time_ms: Tool execution time in milliseconds
            
        Returns:
            Dict with formatted error response (workaround for MCP SDK bug)
        """
        # Log the error with appropriate level and context
        self._log_error(error, tool_name, arguments, execution_time_ms)
        
        # Format error response based on error type
        error_response = self._format_error_response(error, tool_name)
        
        # Return dict directly to avoid MCP SDK serialization bug
        # See: https://github.com/modelcontextprotocol/python-sdk/issues/987
        return {
            "content": [
                {
                    "type": "text",
                    "text": error_response,
                    "annotations": None
                }
            ],
            "isError": True
        }
    
    def _log_error(
        self,
        error: Exception,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_time_ms: Optional[float] = None
    ) -> None:
        """Log error with appropriate level and context.
        
        Args:
            error: Exception to log
            tool_name: Name of the tool that failed
            arguments: Tool arguments
            execution_time_ms: Execution time in milliseconds
        """
        # Prepare logging context
        log_context = {
            "tool_name": tool_name,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        
        # Add execution time if available
        if execution_time_ms is not None:
            log_context["execution_time_ms"] = round(execution_time_ms, 2)
        
        # Add argument keys (not values for security)
        if arguments:
            log_context["argument_keys"] = list(arguments.keys())
        
        # Add specific error context based on error type
        if isinstance(error, SumoLogicError):
            if hasattr(error, 'context') and error.context:
                log_context["error_context"] = error.context
        
        if isinstance(error, APIError):
            if error.status_code:
                log_context["status_code"] = error.status_code
            if error.request_id:
                log_context["request_id"] = error.request_id
        
        if isinstance(error, ValidationError):
            if error.field_name:
                log_context["field_name"] = error.field_name
            if error.validation_errors:
                log_context["validation_errors"] = error.validation_errors
        
        if isinstance(error, RateLimitError):
            if error.retry_after:
                log_context["retry_after"] = error.retry_after
            if error.limit_type:
                log_context["limit_type"] = error.limit_type
        
        if isinstance(error, SearchError):
            if error.job_id:
                log_context["job_id"] = error.job_id
            if error.search_state:
                log_context["search_state"] = error.search_state
        
        if isinstance(error, TimeoutError):
            if error.timeout_seconds:
                log_context["timeout_seconds"] = error.timeout_seconds
            if error.operation:
                log_context["operation"] = error.operation
        
        # Determine log level based on error type
        if isinstance(error, ValidationError):
            # Validation errors are usually user input issues
            self.logger.warning("Tool validation error", **log_context)
        elif isinstance(error, AuthenticationError):
            # Authentication errors are important but not necessarily server issues
            self.logger.error("Tool authentication error", **log_context)
        elif isinstance(error, RateLimitError):
            # Rate limit errors are expected under load
            self.logger.warning("Tool rate limit error", **log_context)
        elif isinstance(error, APIError):
            # API errors could be client or server issues
            if error.is_client_error:
                self.logger.warning("Tool API client error", **log_context)
            else:
                self.logger.error("Tool API server error", **log_context)
        elif isinstance(error, TimeoutError):
            # Timeout errors are usually infrastructure issues
            self.logger.error("Tool timeout error", **log_context)
        elif isinstance(error, SumoLogicError):
            # Other Sumo Logic errors
            self.logger.error("Tool Sumo Logic error", **log_context)
        else:
            # Unexpected errors
            log_context["traceback"] = traceback.format_exc()
            self.logger.error("Tool unexpected error", **log_context)
    
    def _format_error_response(self, error: Exception, tool_name: str) -> str:
        """Format error response for MCP client.
        
        Args:
            error: Exception to format
            tool_name: Name of the tool that failed
            
        Returns:
            Formatted error message string
        """
        if isinstance(error, ValidationError):
            return self._format_validation_error(error, tool_name)
        elif isinstance(error, AuthenticationError):
            return self._format_authentication_error(error, tool_name)
        elif isinstance(error, RateLimitError):
            return self._format_rate_limit_error(error, tool_name)
        elif isinstance(error, APIError):
            return self._format_api_error(error, tool_name)
        elif isinstance(error, SearchError):
            return self._format_search_error(error, tool_name)
        elif isinstance(error, TimeoutError):
            return self._format_timeout_error(error, tool_name)
        elif isinstance(error, ConfigurationError):
            return self._format_configuration_error(error, tool_name)
        elif isinstance(error, SumoLogicError):
            return self._format_sumologic_error(error, tool_name)
        else:
            return self._format_unexpected_error(error, tool_name)
    
    def _format_validation_error(self, error: ValidationError, tool_name: str) -> str:
        """Format validation error response."""
        message = f"Validation Error in {tool_name}: {error.message}"
        
        if error.field_name:
            message += f"\nField: {error.field_name}"
        
        if error.validation_errors:
            message += "\nValidation Details:"
            for field, field_error in error.validation_errors.items():
                message += f"\n  - {field}: {field_error}"
        
        return message
    
    def _format_authentication_error(self, error: AuthenticationError, tool_name: str) -> str:
        """Format authentication error response."""
        message = f"Authentication Error in {tool_name}: {error.message}"
        
        if error.auth_type:
            message += f"\nAuthentication Type: {error.auth_type}"
        
        message += "\nPlease check your Sumo Logic credentials and try again."
        return message
    
    def _format_rate_limit_error(self, error: RateLimitError, tool_name: str) -> str:
        """Format rate limit error response."""
        message = f"Rate Limit Error in {tool_name}: {error.message}"
        
        if error.retry_after:
            message += f"\nRetry after: {error.retry_after} seconds"
        
        if error.limit_type:
            message += f"\nLimit Type: {error.limit_type}"
        
        message += "\nPlease wait before making additional requests."
        return message
    
    def _format_api_error(self, error: APIError, tool_name: str) -> str:
        """Format API error response."""
        message = f"API Error in {tool_name}: {error.message}"
        
        if error.status_code:
            message += f"\nHTTP Status: {error.status_code}"
        
        if error.request_id:
            message += f"\nRequest ID: {error.request_id}"
        
        if error.is_retryable:
            message += "\nThis error may be temporary. Please try again."
        
        return message
    
    def _format_search_error(self, error: SearchError, tool_name: str) -> str:
        """Format search error response."""
        message = f"Search Error in {tool_name}: {error.message}"
        
        if error.job_id:
            message += f"\nJob ID: {error.job_id}"
        
        if error.search_state:
            message += f"\nSearch State: {error.search_state}"
        
        if error.query:
            # Truncate long queries
            query_preview = error.query[:100] + "..." if len(error.query) > 100 else error.query
            message += f"\nQuery: {query_preview}"
        
        return message
    
    def _format_timeout_error(self, error: TimeoutError, tool_name: str) -> str:
        """Format timeout error response."""
        message = f"Timeout Error in {tool_name}: {error.message}"
        
        if error.timeout_seconds:
            message += f"\nTimeout: {error.timeout_seconds} seconds"
        
        if error.operation:
            message += f"\nOperation: {error.operation}"
        
        message += "\nConsider reducing the scope of your request or try again later."
        return message
    
    def _format_configuration_error(self, error: ConfigurationError, tool_name: str) -> str:
        """Format configuration error response."""
        message = f"Configuration Error in {tool_name}: {error.message}"
        
        if error.config_key:
            message += f"\nConfiguration Key: {error.config_key}"
        
        message += "\nPlease check your server configuration and environment variables."
        return message
    
    def _format_sumologic_error(self, error: SumoLogicError, tool_name: str) -> str:
        """Format generic Sumo Logic error response."""
        message = f"Sumo Logic Error in {tool_name}: {error.message}"
        
        if hasattr(error, 'context') and error.context:
            message += f"\nContext: {error.context}"
        
        return message
    
    def _format_unexpected_error(self, error: Exception, tool_name: str) -> str:
        """Format unexpected error response."""
        message = f"Unexpected Error in {tool_name}: {str(error)}"
        message += f"\nError Type: {type(error).__name__}"
        message += "\nThis is an unexpected error. Please report this issue."
        return message
    
    def log_request(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log incoming tool request for debugging.
        
        Args:
            tool_name: Name of the tool being called
            arguments: Tool arguments
            user_context: Optional user context information
        """
        log_context = {
            "tool_name": tool_name,
            "argument_keys": list(arguments.keys()) if arguments else [],
            "argument_count": len(arguments) if arguments else 0
        }
        
        if user_context:
            log_context["user_context"] = user_context
        
        self.logger.debug("Tool request received", **log_context)
    
    def log_response(
        self,
        tool_name: str,
        success: bool,
        execution_time_ms: float,
        response_size: Optional[int] = None
    ) -> None:
        """Log tool response for debugging.
        
        Args:
            tool_name: Name of the tool that was called
            success: Whether the tool execution was successful
            execution_time_ms: Execution time in milliseconds
            response_size: Size of the response data
        """
        log_context = {
            "tool_name": tool_name,
            "success": success,
            "execution_time_ms": round(execution_time_ms, 2)
        }
        
        if response_size is not None:
            log_context["response_size"] = response_size
        
        if success:
            self.logger.info("Tool request completed successfully", **log_context)
        else:
            self.logger.warning("Tool request completed with error", **log_context)
    
    @staticmethod
    def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
        """Configure structured logging for the application.
        
        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_format: Log format (json or text)
        """
        # Configure structlog
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]
        
        # Add appropriate renderer based on format
        if log_format.lower() == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())
        
        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        
        # Configure standard logging
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format="%(message)s" if log_format.lower() == "json" else None
        )