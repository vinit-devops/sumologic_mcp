"""Custom exception classes for Sumo Logic MCP server."""

from typing import Optional, Dict, Any


class SumoLogicError(Exception):
    """Base exception for all Sumo Logic operations.
    
    This is the base class for all custom exceptions in the Sumo Logic MCP server.
    It provides common functionality for error handling and logging.
    """
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Initialize the exception with a message and optional context.
        
        Args:
            message: Human-readable error message
            context: Optional dictionary containing additional error context
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
    
    def __str__(self) -> str:
        """Return string representation of the exception."""
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} (Context: {context_str})"
        return self.message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context
        }


class AuthenticationError(SumoLogicError):
    """Raised when authentication with Sumo Logic fails.
    
    This exception is raised when:
    - Invalid credentials are provided
    - Authentication tokens expire
    - API access is denied due to permissions
    """
    
    def __init__(self, message: str, auth_type: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        """Initialize authentication error.
        
        Args:
            message: Error message describing the authentication failure
            auth_type: Type of authentication that failed (e.g., 'access_key', 'session')
            context: Additional context about the authentication failure
        """
        super().__init__(message, context)
        self.auth_type = auth_type
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.auth_type:
            result["auth_type"] = self.auth_type
        return result


class APIError(SumoLogicError):
    """Raised when Sumo Logic API calls fail.
    
    This exception is raised when:
    - HTTP requests to Sumo Logic APIs fail
    - API returns error status codes
    - Response parsing fails
    """
    
    def __init__(
        self, 
        message: str, 
        status_code: Optional[int] = None, 
        response_body: Optional[str] = None,
        request_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize API error.
        
        Args:
            message: Error message describing the API failure
            status_code: HTTP status code from the failed request
            response_body: Raw response body from the failed request
            request_id: Request ID for tracking the failed request
            context: Additional context about the API failure
        """
        super().__init__(message, context)
        self.status_code = status_code
        self.response_body = response_body
        self.request_id = request_id
    
    def __str__(self) -> str:
        """Return string representation including status code."""
        base_str = super().__str__()
        if self.status_code:
            return f"{base_str} (HTTP {self.status_code})"
        return base_str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.status_code:
            result["status_code"] = self.status_code
        if self.response_body:
            result["response_body"] = self.response_body
        if self.request_id:
            result["request_id"] = self.request_id
        return result
    
    @property
    def is_client_error(self) -> bool:
        """Check if this is a client error (4xx status code)."""
        return self.status_code is not None and 400 <= self.status_code < 500
    
    @property
    def is_server_error(self) -> bool:
        """Check if this is a server error (5xx status code)."""
        return self.status_code is not None and 500 <= self.status_code < 600
    
    @property
    def is_retryable(self) -> bool:
        """Check if this error might be retryable."""
        # Generally, server errors and some client errors are retryable
        if self.is_server_error:
            return True
        # Some 4xx errors are retryable (e.g., 408 Request Timeout, 429 Too Many Requests)
        if self.status_code in [408, 429]:
            return True
        return False


class RateLimitError(APIError):
    """Raised when API rate limits are exceeded.
    
    This exception is raised when:
    - Too many requests are made in a short time period
    - API quota limits are reached
    - Throttling is applied by Sumo Logic
    """
    
    def __init__(
        self, 
        message: str, 
        retry_after: Optional[int] = None,
        limit_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize rate limit error.
        
        Args:
            message: Error message describing the rate limit
            retry_after: Number of seconds to wait before retrying
            limit_type: Type of rate limit (e.g., 'requests_per_minute', 'concurrent_searches')
            context: Additional context about the rate limit
        """
        super().__init__(message, status_code=429, context=context)
        self.retry_after = retry_after
        self.limit_type = limit_type
    
    def __str__(self) -> str:
        """Return string representation including retry information."""
        base_str = super().__str__()
        if self.retry_after:
            return f"{base_str} (Retry after {self.retry_after} seconds)"
        return base_str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.retry_after:
            result["retry_after"] = self.retry_after
        if self.limit_type:
            result["limit_type"] = self.limit_type
        return result


class ValidationError(SumoLogicError):
    """Raised when input validation fails.
    
    This exception is raised when:
    - Request parameters are invalid
    - Configuration values are malformed
    - Data model validation fails
    """
    
    def __init__(
        self, 
        message: str, 
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        validation_errors: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize validation error.
        
        Args:
            message: Error message describing the validation failure
            field_name: Name of the field that failed validation
            field_value: Value that failed validation
            validation_errors: Dictionary of field names to validation error messages
            context: Additional context about the validation failure
        """
        super().__init__(message, context)
        self.field_name = field_name
        self.field_value = field_value
        self.validation_errors = validation_errors or {}
    
    def __str__(self) -> str:
        """Return string representation including field information."""
        base_str = super().__str__()
        if self.field_name:
            return f"{base_str} (Field: {self.field_name})"
        return base_str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.field_name:
            result["field_name"] = self.field_name
        if self.field_value is not None:
            result["field_value"] = str(self.field_value)
        if self.validation_errors:
            result["validation_errors"] = self.validation_errors
        return result


class ConfigurationError(SumoLogicError):
    """Raised when server configuration is invalid.
    
    This exception is raised when:
    - Required configuration values are missing
    - Configuration values are invalid
    - Environment setup is incorrect
    """
    
    def __init__(
        self, 
        message: str, 
        config_key: Optional[str] = None,
        config_value: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize configuration error.
        
        Args:
            message: Error message describing the configuration issue
            config_key: Configuration key that has the issue
            config_value: Configuration value that is invalid
            context: Additional context about the configuration error
        """
        super().__init__(message, context)
        self.config_key = config_key
        self.config_value = config_value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.config_key:
            result["config_key"] = self.config_key
        if self.config_value:
            result["config_value"] = self.config_value
        return result


class SearchError(SumoLogicError):
    """Raised when search operations fail.
    
    This exception is raised when:
    - Search queries are malformed
    - Search jobs fail or timeout
    - Search results cannot be retrieved
    """
    
    def __init__(
        self, 
        message: str, 
        job_id: Optional[str] = None,
        query: Optional[str] = None,
        search_state: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize search error.
        
        Args:
            message: Error message describing the search failure
            job_id: Search job ID if applicable
            query: Search query that failed
            search_state: Current state of the search job
            context: Additional context about the search error
        """
        super().__init__(message, context)
        self.job_id = job_id
        self.query = query
        self.search_state = search_state
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.job_id:
            result["job_id"] = self.job_id
        if self.query:
            result["query"] = self.query
        if self.search_state:
            result["search_state"] = self.search_state
        return result


class TimeoutError(SumoLogicError):
    """Raised when operations timeout.
    
    This exception is raised when:
    - API requests exceed timeout limits
    - Search jobs take too long to complete
    - Connection timeouts occur
    """
    
    def __init__(
        self, 
        message: str, 
        timeout_seconds: Optional[float] = None,
        operation: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize timeout error.
        
        Args:
            message: Error message describing the timeout
            timeout_seconds: Timeout duration in seconds
            operation: Operation that timed out
            context: Additional context about the timeout
        """
        super().__init__(message, context)
        self.timeout_seconds = timeout_seconds
        self.operation = operation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        result = super().to_dict()
        if self.timeout_seconds:
            result["timeout_seconds"] = self.timeout_seconds
        if self.operation:
            result["operation"] = self.operation
        return result


# Export all exception classes
__all__ = [
    'SumoLogicError',
    'AuthenticationError', 
    'APIError',
    'RateLimitError',
    'ValidationError',
    'ConfigurationError',
    'SearchError',
    'TimeoutError'
]