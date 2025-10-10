"""
Enhanced error handling and logging specifically for monitor tools.

This module provides specialized error handling patterns for monitor operations,
including monitor-specific error types, retry logic, and comprehensive logging.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Union, Callable
from datetime import datetime, timedelta
import structlog

from ..exceptions import (
    APIError, 
    RateLimitError, 
    ValidationError, 
    TimeoutError,
    SumoLogicError
)
from ..resilience import (
    ResilientAPIClient,
    RetryConfig,
    CircuitBreakerConfig,
    TimeoutManager
)


logger = structlog.get_logger(__name__)


class MonitorError(SumoLogicError):
    """Base exception for monitor-specific operations."""
    
    def __init__(
        self, 
        message: str, 
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor error.
        
        Args:
            message: Error message
            monitor_id: ID of the monitor involved in the error
            monitor_name: Name of the monitor involved in the error
            operation: Monitor operation that failed
            context: Additional error context
        """
        super().__init__(message, context)
        self.monitor_id = monitor_id
        self.monitor_name = monitor_name
        self.operation = operation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.monitor_id:
            result["monitor_id"] = self.monitor_id
        if self.monitor_name:
            result["monitor_name"] = self.monitor_name
        if self.operation:
            result["operation"] = self.operation
        return result


class MonitorValidationError(MonitorError, ValidationError):
    """Raised when monitor configuration validation fails."""
    
    def __init__(
        self,
        message: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        validation_errors: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor validation error."""
        MonitorError.__init__(self, message, monitor_id, monitor_name, "validation", context)
        ValidationError.__init__(self, message, field_name, field_value, validation_errors, context)


class MonitorNotFoundError(MonitorError):
    """Raised when a monitor is not found."""
    
    def __init__(
        self,
        monitor_id: str,
        message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor not found error."""
        if message is None:
            message = f"Monitor with ID '{monitor_id}' not found"
        super().__init__(message, monitor_id=monitor_id, operation="get", context=context)


class MonitorPermissionError(MonitorError):
    """Raised when insufficient permissions for monitor operations."""
    
    def __init__(
        self,
        message: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        operation: Optional[str] = None,
        required_permission: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor permission error."""
        super().__init__(message, monitor_id, monitor_name, operation, context)
        self.required_permission = required_permission
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.required_permission:
            result["required_permission"] = self.required_permission
        return result


class MonitorConfigurationError(MonitorError):
    """Raised when monitor configuration is invalid or incompatible."""
    
    def __init__(
        self,
        message: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        config_section: Optional[str] = None,
        config_errors: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor configuration error."""
        super().__init__(message, monitor_id, monitor_name, "configuration", context)
        self.config_section = config_section
        self.config_errors = config_errors or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.config_section:
            result["config_section"] = self.config_section
        if self.config_errors:
            result["config_errors"] = self.config_errors
        return result


class MonitorOperationError(MonitorError):
    """Raised when monitor operations fail due to state or business logic issues."""
    
    def __init__(
        self,
        message: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        operation: Optional[str] = None,
        monitor_state: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize monitor operation error."""
        super().__init__(message, monitor_id, monitor_name, operation, context)
        self.monitor_state = monitor_state
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.monitor_state:
            result["monitor_state"] = self.monitor_state
        return result


class MonitorErrorHandler:
    """Enhanced error handler specifically for monitor operations."""
    
    def __init__(self, tool_name: str = "monitor_tools"):
        """Initialize monitor error handler.
        
        Args:
            tool_name: Name of the monitor tool for logging context
        """
        self.tool_name = tool_name
        self.logger = logger.bind(tool_name=tool_name)
        
        # Track error patterns for monitoring
        self.error_counts: Dict[str, int] = {}
        self.last_error_times: Dict[str, datetime] = {}
        
        # Initialize resilient client for monitor operations
        self.resilient_client = self._create_resilient_client()
        
        # Initialize timeout manager with monitor-specific timeouts
        self.timeout_manager = TimeoutManager(default_timeout=30.0)
        self._setup_monitor_timeouts()
    
    def _create_resilient_client(self) -> ResilientAPIClient:
        """Create resilient client with monitor-specific configuration."""
        retry_config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                APIError, RateLimitError, TimeoutError, 
                ConnectionError, OSError, MonitorError
            )
        )
        
        circuit_breaker_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60.0,
            expected_exception=Exception,
            success_threshold=3
        )
        
        return ResilientAPIClient(
            name="monitor-operations",
            retry_config=retry_config,
            circuit_breaker_config=circuit_breaker_config
        )
    
    def _setup_monitor_timeouts(self):
        """Setup monitor operation-specific timeouts."""
        self.timeout_manager.set_timeout("list_monitors", 30.0)
        self.timeout_manager.set_timeout("get_monitor", 15.0)
        self.timeout_manager.set_timeout("create_monitor", 45.0)
        self.timeout_manager.set_timeout("update_monitor", 30.0)
        self.timeout_manager.set_timeout("delete_monitor", 20.0)
        self.timeout_manager.set_timeout("get_monitor_status", 25.0)
        self.timeout_manager.set_timeout("get_active_alerts", 20.0)
        self.timeout_manager.set_timeout("enable_monitor", 15.0)
        self.timeout_manager.set_timeout("disable_monitor", 15.0)
        self.timeout_manager.set_timeout("validate_monitor_config", 10.0)
        self.timeout_manager.set_timeout("get_monitor_history", 60.0)
    
    async def execute_with_error_handling(
        self,
        operation: str,
        func: Callable,
        *args,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        timeout_override: Optional[float] = None,
        **kwargs
    ) -> Any:
        """Execute monitor operation with comprehensive error handling.
        
        Args:
            operation: Name of the monitor operation
            func: Function to execute
            *args: Positional arguments for function
            monitor_id: Optional monitor ID for context
            monitor_name: Optional monitor name for context
            timeout_override: Optional timeout override
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            MonitorError: Enhanced monitor-specific error with context
        """
        start_time = time.time()
        
        # Log operation start
        self.logger.info(
            f"Starting monitor operation: {operation}",
            operation=operation,
            monitor_id=monitor_id,
            monitor_name=monitor_name
        )
        
        try:
            # Execute with timeout and resilience patterns
            result = await self.timeout_manager.execute_with_timeout(
                self._execute_with_resilience,
                operation,
                func,
                *args,
                timeout=timeout_override,
                **kwargs
            )
            
            # Log successful completion
            execution_time = (time.time() - start_time) * 1000
            self.logger.info(
                f"Monitor operation completed successfully: {operation}",
                operation=operation,
                monitor_id=monitor_id,
                monitor_name=monitor_name,
                execution_time_ms=round(execution_time, 2)
            )
            
            return result
            
        except Exception as e:
            # Enhanced error handling with context
            execution_time = (time.time() - start_time) * 1000
            enhanced_error = await self._enhance_error(
                e, operation, monitor_id, monitor_name, execution_time
            )
            
            # Track error patterns
            self._track_error_pattern(operation, enhanced_error)
            
            # Log error with full context
            self._log_enhanced_error(enhanced_error, operation, execution_time)
            
            raise enhanced_error
    
    async def _execute_with_resilience(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with resilience patterns."""
        return await self.resilient_client.execute(func, *args, **kwargs)
    
    async def _enhance_error(
        self,
        error: Exception,
        operation: str,
        monitor_id: Optional[str],
        monitor_name: Optional[str],
        execution_time_ms: float
    ) -> Exception:
        """Enhance error with monitor-specific context and classification.
        
        Args:
            error: Original exception
            operation: Monitor operation that failed
            monitor_id: Monitor ID if available
            monitor_name: Monitor name if available
            execution_time_ms: Execution time in milliseconds
            
        Returns:
            Enhanced exception with monitor context
        """
        # Build error context
        error_context = {
            "operation": operation,
            "execution_time_ms": round(execution_time_ms, 2),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if monitor_id:
            error_context["monitor_id"] = monitor_id
        if monitor_name:
            error_context["monitor_name"] = monitor_name
        
        # Classify and enhance error based on type and content
        if isinstance(error, APIError):
            return await self._enhance_api_error(error, operation, error_context)
        elif isinstance(error, ValidationError):
            return await self._enhance_validation_error(error, operation, error_context)
        elif isinstance(error, TimeoutError):
            return await self._enhance_timeout_error(error, operation, error_context)
        elif isinstance(error, RateLimitError):
            return await self._enhance_rate_limit_error(error, operation, error_context)
        elif isinstance(error, MonitorError):
            # Already a monitor error, just add context
            error.context.update(error_context)
            return error
        else:
            # Convert to generic monitor error
            return MonitorError(
                f"Unexpected error in {operation}: {str(error)}",
                monitor_id=monitor_id,
                monitor_name=monitor_name,
                operation=operation,
                context=error_context
            )
    
    async def _enhance_api_error(
        self, 
        error: APIError, 
        operation: str, 
        context: Dict[str, Any]
    ) -> Exception:
        """Enhance API error with monitor-specific classification."""
        # Classify based on status code and operation
        if error.status_code == 404:
            monitor_id = context.get("monitor_id")
            if monitor_id and operation in ["get_monitor", "update_monitor", "delete_monitor"]:
                return MonitorNotFoundError(
                    monitor_id=monitor_id,
                    context=context
                )
        
        elif error.status_code == 403:
            return MonitorPermissionError(
                message=f"Insufficient permissions for monitor {operation}",
                monitor_id=context.get("monitor_id"),
                monitor_name=context.get("monitor_name"),
                operation=operation,
                context=context
            )
        
        elif error.status_code == 400:
            # Check if it's a configuration error
            if "configuration" in str(error).lower() or "invalid" in str(error).lower():
                return MonitorConfigurationError(
                    message=f"Invalid monitor configuration in {operation}: {error.message}",
                    monitor_id=context.get("monitor_id"),
                    monitor_name=context.get("monitor_name"),
                    context=context
                )
        
        elif error.status_code == 409:
            return MonitorOperationError(
                message=f"Monitor operation conflict in {operation}: {error.message}",
                monitor_id=context.get("monitor_id"),
                monitor_name=context.get("monitor_name"),
                operation=operation,
                context=context
            )
        
        # Default: enhance existing API error with monitor context
        error.context.update(context)
        return error
    
    async def _enhance_validation_error(
        self, 
        error: ValidationError, 
        operation: str, 
        context: Dict[str, Any]
    ) -> MonitorValidationError:
        """Enhance validation error with monitor context."""
        return MonitorValidationError(
            message=f"Monitor validation failed in {operation}: {error.message}",
            monitor_id=context.get("monitor_id"),
            monitor_name=context.get("monitor_name"),
            field_name=error.field_name,
            field_value=error.field_value,
            validation_errors=error.validation_errors,
            context=context
        )
    
    async def _enhance_timeout_error(
        self, 
        error: TimeoutError, 
        operation: str, 
        context: Dict[str, Any]
    ) -> MonitorError:
        """Enhance timeout error with monitor context."""
        return MonitorError(
            message=f"Monitor operation {operation} timed out: {error.message}",
            monitor_id=context.get("monitor_id"),
            monitor_name=context.get("monitor_name"),
            operation=operation,
            context=context
        )
    
    async def _enhance_rate_limit_error(
        self, 
        error: RateLimitError, 
        operation: str, 
        context: Dict[str, Any]
    ) -> RateLimitError:
        """Enhance rate limit error with monitor context."""
        error.context.update(context)
        return error
    
    def _track_error_pattern(self, operation: str, error: Exception):
        """Track error patterns for monitoring and alerting."""
        error_key = f"{operation}:{type(error).__name__}"
        
        # Increment error count
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Update last error time
        self.last_error_times[error_key] = datetime.utcnow()
        
        # Check for error rate thresholds
        if self.error_counts[error_key] >= 5:
            # Log high error rate warning
            self.logger.warning(
                f"High error rate detected for {operation}",
                operation=operation,
                error_type=type(error).__name__,
                error_count=self.error_counts[error_key],
                time_window="recent"
            )
    
    def _log_enhanced_error(
        self, 
        error: Exception, 
        operation: str, 
        execution_time_ms: float
    ):
        """Log enhanced error with appropriate level and context."""
        log_context = {
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "execution_time_ms": round(execution_time_ms, 2)
        }
        
        # Add monitor-specific context if available
        if isinstance(error, MonitorError):
            if error.monitor_id:
                log_context["monitor_id"] = error.monitor_id
            if error.monitor_name:
                log_context["monitor_name"] = error.monitor_name
            if error.context:
                log_context["error_context"] = error.context
        
        # Add API error context
        if isinstance(error, APIError):
            if error.status_code:
                log_context["status_code"] = error.status_code
            if error.request_id:
                log_context["request_id"] = error.request_id
        
        # Add validation error context
        if isinstance(error, (ValidationError, MonitorValidationError)):
            if hasattr(error, 'field_name') and error.field_name:
                log_context["field_name"] = error.field_name
            if hasattr(error, 'validation_errors') and error.validation_errors:
                log_context["validation_errors"] = error.validation_errors
        
        # Determine log level based on error type and severity
        if isinstance(error, (MonitorValidationError, ValidationError)):
            self.logger.warning("Monitor validation error", **log_context)
        elif isinstance(error, MonitorNotFoundError):
            self.logger.warning("Monitor not found", **log_context)
        elif isinstance(error, MonitorPermissionError):
            self.logger.error("Monitor permission denied", **log_context)
        elif isinstance(error, MonitorConfigurationError):
            self.logger.error("Monitor configuration error", **log_context)
        elif isinstance(error, RateLimitError):
            self.logger.warning("Monitor operation rate limited", **log_context)
        elif isinstance(error, TimeoutError):
            self.logger.error("Monitor operation timeout", **log_context)
        elif isinstance(error, APIError):
            if error.is_client_error:
                self.logger.warning("Monitor API client error", **log_context)
            else:
                self.logger.error("Monitor API server error", **log_context)
        else:
            self.logger.error("Monitor operation error", **log_context)
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics for monitoring and debugging."""
        current_time = datetime.utcnow()
        recent_errors = {}
        
        # Calculate recent error rates (last 5 minutes)
        for error_key, last_time in self.last_error_times.items():
            if current_time - last_time <= timedelta(minutes=5):
                recent_errors[error_key] = {
                    "count": self.error_counts.get(error_key, 0),
                    "last_occurrence": last_time.isoformat()
                }
        
        return {
            "total_error_types": len(self.error_counts),
            "total_errors": sum(self.error_counts.values()),
            "recent_errors": recent_errors,
            "circuit_breaker_status": self.resilient_client.get_health_status(),
            "error_patterns": dict(self.error_counts)
        }
    
    def reset_error_statistics(self):
        """Reset error statistics (useful for testing or periodic cleanup)."""
        self.error_counts.clear()
        self.last_error_times.clear()
        
        self.logger.info("Reset monitor error statistics")


# Utility functions for common error handling patterns

async def validate_monitor_id(monitor_id: Optional[str], operation: str = "monitor_operation") -> str:
    """Validate monitor ID parameter.
    
    Args:
        monitor_id: Monitor ID to validate
        operation: Operation name for error context
        
    Returns:
        Validated and cleaned monitor ID
        
    Raises:
        MonitorValidationError: If monitor ID is invalid
    """
    if not monitor_id:
        raise MonitorValidationError(
            "Monitor ID is required",
            field_name="monitor_id",
            field_value=monitor_id,
            context={"operation": operation}
        )
    
    monitor_id = monitor_id.strip()
    if not monitor_id:
        raise MonitorValidationError(
            "Monitor ID cannot be empty or whitespace",
            field_name="monitor_id",
            field_value=monitor_id,
            context={"operation": operation}
        )
    
    # Basic format validation (Sumo Logic monitor IDs are typically hex strings)
    if len(monitor_id) < 8 or len(monitor_id) > 64:
        raise MonitorValidationError(
            "Monitor ID must be between 8 and 64 characters",
            field_name="monitor_id",
            field_value=monitor_id,
            context={"operation": operation}
        )
    
    return monitor_id


async def validate_pagination_params(
    limit: int = 100, 
    offset: int = 0, 
    operation: str = "list_operation"
) -> tuple[int, int]:
    """Validate pagination parameters.
    
    Args:
        limit: Maximum number of items to return
        offset: Starting position for pagination
        operation: Operation name for error context
        
    Returns:
        Tuple of validated (limit, offset)
        
    Raises:
        MonitorValidationError: If pagination parameters are invalid
    """
    if limit < 1 or limit > 1000:
        raise MonitorValidationError(
            "Limit must be between 1 and 1000",
            field_name="limit",
            field_value=limit,
            context={"operation": operation}
        )
    
    if offset < 0:
        raise MonitorValidationError(
            "Offset must be non-negative",
            field_name="offset",
            field_value=offset,
            context={"operation": operation}
        )
    
    return limit, offset


def create_monitor_error_context(
    operation: str,
    monitor_id: Optional[str] = None,
    monitor_name: Optional[str] = None,
    **additional_context
) -> Dict[str, Any]:
    """Create standardized error context for monitor operations.
    
    Args:
        operation: Monitor operation name
        monitor_id: Optional monitor ID
        monitor_name: Optional monitor name
        **additional_context: Additional context fields
        
    Returns:
        Dictionary with standardized error context
    """
    context = {
        "operation": operation,
        "timestamp": datetime.utcnow().isoformat(),
        "tool": "monitor_tools"
    }
    
    if monitor_id:
        context["monitor_id"] = monitor_id
    if monitor_name:
        context["monitor_name"] = monitor_name
    
    context.update(additional_context)
    return context