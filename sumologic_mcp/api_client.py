"""API client layer for Sumo Logic MCP server."""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from urllib.parse import urljoin, urlencode

import httpx
from pydantic import ValidationError as PydanticValidationError

from .auth import SumoLogicAuth
from .config import SumoLogicConfig, SearchRequest, DashboardConfig
from .models.config import MetricsRequest, CollectorConfig, SourceConfig
from .exceptions import (
    APIError, 
    RateLimitError, 
    ValidationError, 
    TimeoutError,
    SearchError,
    SumoLogicError,
    TimeValidationError,
    APIParameterError
)
from .resilience import (
    ResilientAPIClient,
    RetryConfig,
    CircuitBreakerConfig,
    TimeoutManager
)
from .api_validator import SumoLogicAPIValidator
from .monitoring import MetricsCollector
from .time_utils import TimeParser


logger = logging.getLogger(__name__)


class SumoLogicAPIClient:
    """Low-level client for Sumo Logic REST APIs.
    
    This class provides a comprehensive interface to Sumo Logic's REST APIs,
    including search, dashboard, metrics, and collector management operations.
    It handles authentication, rate limiting, retries, and error handling.
    
    Attributes:
        config: Sumo Logic configuration
        auth: Authentication manager
        http_client: HTTP client for API requests
    """
    
    def __init__(self, config: SumoLogicConfig, auth: SumoLogicAuth):
        """Initialize API client with configuration and authentication.
        
        Args:
            config: Sumo Logic configuration containing API settings
            auth: Authentication manager for handling credentials
        """
        self.config = config
        self.auth = auth
        self._http_client: Optional[httpx.AsyncClient] = None
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time = 0.0
        
        # Initialize resilience components
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.rate_limit_delay,
            max_delay=min(self.config.timeout / 2, 60.0),  # Don't exceed half timeout
            retryable_exceptions=(
                APIError, RateLimitError, TimeoutError, 
                ConnectionError, OSError, httpx.RequestError
            )
        )
        
        circuit_breaker_config = CircuitBreakerConfig(
            failure_threshold=max(5, self.config.max_retries * 2),
            recovery_timeout=60.0,
            expected_exception=Exception,
            success_threshold=3
        )
        
        self.resilient_client = ResilientAPIClient(
            name="sumologic-api",
            retry_config=retry_config,
            circuit_breaker_config=circuit_breaker_config
        )
        
        # Initialize timeout manager with operation-specific timeouts
        self.timeout_manager = TimeoutManager(default_timeout=self.config.timeout)
        self._setup_operation_timeouts()
        
        # Initialize metrics collector
        self.metrics_collector = MetricsCollector()
        
        logger.info(
            "Initialized Sumo Logic API client with resilience patterns and monitoring",
            extra={
                "endpoint": self.config.endpoint,
                "timeout": self.config.timeout,
                "max_retries": self.config.max_retries,
                "circuit_breaker_threshold": circuit_breaker_config.failure_threshold
            }
        )
    
    def _setup_operation_timeouts(self):
        """Setup operation-specific timeouts."""
        # Search operations may take longer
        self.timeout_manager.set_timeout("search", self.config.timeout * 2)
        self.timeout_manager.set_timeout("search_results", self.config.timeout * 1.5)
        
        # Dashboard operations are usually quick
        self.timeout_manager.set_timeout("dashboard", self.config.timeout)
        
        # Metrics queries can be complex
        self.timeout_manager.set_timeout("metrics", self.config.timeout * 1.5)
        
        # Collector operations are typically fast
        self.timeout_manager.set_timeout("collector", self.config.timeout)
        
        # Monitor operations are usually quick
        self.timeout_manager.set_timeout("monitor", self.config.timeout)
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for API requests.
        
        Returns:
            Configured HTTP client instance
        """
        if self._http_client is None:
            # Check if SSL verification should be disabled
            import os
            verify_ssl = os.getenv('PYTHONHTTPSVERIFY', '1') != '0'
            
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                verify=verify_ssl,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers={
                    "User-Agent": f"sumologic-mcp-server/{self.config.server_version}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            )
        return self._http_client
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        operation_type: str = "api"
    ) -> httpx.Response:
        """Make HTTP request with resilience patterns.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body
            headers: Additional headers
            operation_type: Type of operation for timeout management
            
        Returns:
            HTTP response object
            
        Raises:
            APIError: If request fails after all retries
            RateLimitError: If rate limit is exceeded
            TimeoutError: If request times out
        """
        # Record request metrics
        await self.metrics_collector.increment_counter(
            "api_requests_total",
            labels={"method": method, "operation": operation_type}
        )
        
        request_start_time = time.time()
        
        # Use resilient client to execute the request with retry and circuit breaker
        async def make_single_request() -> httpx.Response:
            # Apply rate limiting
            await self._apply_rate_limiting()
            
            # Build full URL
            url = urljoin(self.config.endpoint, endpoint.lstrip('/'))
            
            # Get authentication headers
            try:
                auth_headers = await self.auth.get_auth_headers()
            except Exception as e:
                raise APIError(
                    f"Failed to get authentication headers: {e}",
                    context={"endpoint": endpoint, "method": method}
                ) from e
            
            # Merge headers
            request_headers = auth_headers.copy()
            if headers:
                request_headers.update(headers)
            
            # Log request details
            logger.debug(
                f"Making {method} request to {endpoint}",
                extra={
                    "url": url,
                    "params": params,
                    "has_json_data": json_data is not None,
                    "operation_type": operation_type
                }
            )
            
            # Execute request with timeout
            response = await self.timeout_manager.execute_with_timeout(
                self._execute_http_request,
                operation_type,
                method, url, params, json_data, request_headers
            )
            
            # Handle response and errors
            await self._handle_response_errors(response, endpoint, method)
            
            return response
        
        try:
            # Execute with resilience patterns
            response = await self.resilient_client.execute(make_single_request)
            
            # Record success metrics
            request_duration = (time.time() - request_start_time) * 1000
            await self.metrics_collector.increment_counter(
                "api_requests_success_total",
                labels={"method": method, "operation": operation_type}
            )
            await self.metrics_collector.record_timer(
                "api_request_duration_ms",
                request_duration,
                labels={"method": method, "operation": operation_type}
            )
            
            return response
            
        except Exception as e:
            # Record failure metrics
            request_duration = (time.time() - request_start_time) * 1000
            await self.metrics_collector.increment_counter(
                "api_requests_failure_total",
                labels={
                    "method": method,
                    "operation": operation_type,
                    "error_type": type(e).__name__
                }
            )
            await self.metrics_collector.record_timer(
                "api_request_duration_ms",
                request_duration,
                labels={
                    "method": method,
                    "operation": operation_type,
                    "status": "failure"
                }
            )
            raise
    
    async def _execute_http_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]],
        json_data: Optional[Dict[str, Any]],
        headers: Dict[str, str]
    ) -> httpx.Response:
        """Execute the actual HTTP request.
        
        Args:
            method: HTTP method
            url: Full URL
            params: Query parameters
            json_data: JSON request body
            headers: Request headers
            
        Returns:
            HTTP response
        """
        try:
            response = await self.http_client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers
            )
            
            # Log response details
            logger.debug(
                f"Received response",
                extra={
                    "status_code": response.status_code,
                    "response_size": len(response.content) if response.content else 0,
                    "request_id": response.headers.get("x-sumo-request-id"),
                    "url": url
                }
            )
            
            return response
            
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Request to {url} timed out",
                timeout_seconds=self.config.timeout,
                operation=f"{method} {url}"
            ) from e
        
        except httpx.RequestError as e:
            raise APIError(
                f"Request to {url} failed: {e}",
                context={
                    "method": method,
                    "url": url,
                    "error_type": type(e).__name__
                }
            ) from e
    
    async def _handle_response_errors(
        self,
        response: httpx.Response,
        endpoint: str,
        method: str
    ) -> None:
        """Handle HTTP response errors.
        
        Args:
            response: HTTP response to check
            endpoint: API endpoint
            method: HTTP method
            
        Raises:
            RateLimitError: If rate limited
            APIError: For other HTTP errors
        """
        # Handle rate limiting
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response)
            raise RateLimitError(
                f"Rate limit exceeded for {endpoint}",
                retry_after=retry_after,
                limit_type="api_requests",
                context={
                    "endpoint": endpoint,
                    "method": method
                }
            )
        
        # Handle authentication errors
        if response.status_code == 401:
            raise APIError(
                "Authentication failed - invalid or expired credentials",
                status_code=401,
                response_body=response.text,
                request_id=response.headers.get("x-sumo-request-id"),
                context={"endpoint": endpoint, "method": method}
            )
        
        # Handle client errors (4xx)
        if 400 <= response.status_code < 500:
            error_message = f"Client error {response.status_code} for {endpoint}"
            
            # Try to extract error details from response
            try:
                error_data = response.json()
                if isinstance(error_data, dict) and "message" in error_data:
                    error_message = error_data["message"]
            except (json.JSONDecodeError, ValueError):
                error_message = response.text or error_message
            
            raise APIError(
                error_message,
                status_code=response.status_code,
                response_body=response.text,
                request_id=response.headers.get("x-sumo-request-id"),
                context={"endpoint": endpoint, "method": method}
            )
        
        # Handle server errors (5xx)
        if response.status_code >= 500:
            raise APIError(
                f"Server error {response.status_code} for {endpoint}",
                status_code=response.status_code,
                response_body=response.text,
                request_id=response.headers.get("x-sumo-request-id"),
                context={"endpoint": endpoint, "method": method}
            )
    
    async def _apply_rate_limiting(self) -> None:
        """Apply rate limiting to prevent exceeding API limits."""
        async with self._rate_limit_lock:
            current_time = asyncio.get_event_loop().time()
            time_since_last = current_time - self._last_request_time
            
            if time_since_last < self.config.rate_limit_delay:
                sleep_time = self.config.rate_limit_delay - time_since_last
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                await asyncio.sleep(sleep_time)
            
            self._last_request_time = asyncio.get_event_loop().time()
    
    def _parse_retry_after(self, response: httpx.Response) -> float:
        """Parse Retry-After header from rate limit response.
        
        Args:
            response: HTTP response with rate limit error
            
        Returns:
            Number of seconds to wait before retrying
        """
        retry_after_header = response.headers.get("Retry-After")
        
        if retry_after_header:
            try:
                # Try parsing as seconds
                return float(retry_after_header)
            except ValueError:
                # Try parsing as HTTP date
                try:
                    from email.utils import parsedate_to_datetime
                    retry_time = parsedate_to_datetime(retry_after_header)
                    return max(0, (retry_time - datetime.utcnow()).total_seconds())
                except (ValueError, TypeError):
                    pass
        
        # Default backoff if no valid Retry-After header
        return self.config.rate_limit_delay * 2
    
    async def _parse_json_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Parse JSON response with error handling.
        
        Args:
            response: HTTP response to parse
            
        Returns:
            Parsed JSON data
            
        Raises:
            APIError: If response cannot be parsed as JSON
        """
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise APIError(
                f"Failed to parse JSON response: {e}",
                status_code=response.status_code,
                response_body=response.text,
                request_id=response.headers.get("x-sumo-request-id"),
                context={"content_type": response.headers.get("content-type")}
            ) from e
    
    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        
        logger.info("Sumo Logic API client closed")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the API client including resilience metrics.
        
        Returns:
            Dictionary containing health status and metrics
        """
        resilience_status = self.resilient_client.get_health_status()
        metrics_summary = await self.metrics_collector.get_metrics_summary()
        
        return {
            "api_client": {
                "endpoint": self.config.endpoint,
                "timeout": self.config.timeout,
                "max_retries": self.config.max_retries,
                "rate_limit_delay": self.config.rate_limit_delay,
                "http_client_active": self._http_client is not None
            },
            "resilience": resilience_status,
            "timeouts": {
                "default": self.timeout_manager.default_timeout,
                "operations": dict(self.timeout_manager.operation_timeouts)
            },
            "metrics": metrics_summary
        }
    
    async def reset_circuit_breaker(self) -> Dict[str, Any]:
        """Reset the circuit breaker to allow new requests.
        
        This method can be used when the circuit breaker is open due to
        previous failures but you want to test connectivity again.
        
        Returns:
            Dictionary containing reset status and circuit breaker state
        """
        try:
            # Reset the circuit breaker
            self.resilient_client.circuit_breaker.reset()
            
            logger.info("Circuit breaker has been reset")
            
            # Get updated status
            resilience_status = self.resilient_client.get_health_status()
            
            return {
                "reset_successful": True,
                "timestamp": datetime.utcnow().isoformat(),
                "circuit_breaker_state": resilience_status.get("circuit_breaker", {}),
                "message": "Circuit breaker has been reset and is now closed"
            }
            
        except Exception as e:
            logger.error(f"Failed to reset circuit breaker: {e}")
            return {
                "reset_successful": False,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "message": "Failed to reset circuit breaker"
            }
    
    def is_circuit_breaker_open(self) -> bool:
        """Check if the circuit breaker is currently open.
        
        Returns:
            True if circuit breaker is open (blocking requests), False otherwise
        """
        try:
            health_status = self.resilient_client.get_health_status()
            circuit_breaker_status = health_status.get("circuit_breaker", {})
            return circuit_breaker_status.get("state") == "open"
        except Exception:
            return False
    
    async def get_api_metrics(self) -> Dict[str, Any]:
        """Get API-specific metrics.
        
        Returns:
            Dictionary containing API metrics
        """
        return await self.metrics_collector.get_all_metrics()
    
    # Search API Methods
    
    async def search_logs(
        self,
        query: str,
        from_time: str,
        to_time: str,
        limit: int = 100,
        offset: int = 0,
        time_zone: Optional[str] = None,
        by_receipt_time: bool = False,
        auto_parsing_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute log search query.
        
        Args:
            query: Search query string
            from_time: Start time (ISO format, relative like '-1h', epoch, or 'now')
            to_time: End time (ISO format, relative like 'now', epoch, or 'now')
            limit: Maximum results to return (1-10000)
            offset: Result offset for pagination
            time_zone: Time zone for query (e.g., 'UTC', 'America/New_York')
            by_receipt_time: Search by receipt time instead of message time
            auto_parsing_mode: Auto parsing mode ('intelligent', 'performance')
            
        Returns:
            Dictionary containing search job information
            
        Raises:
            ValidationError: If search parameters are invalid
            SearchError: If search execution fails
            APIError: If API request fails
        """
        # First validate using SearchRequest model for comprehensive validation
        try:
            search_request = SearchRequest(
                query=query,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                offset=offset,
                time_zone=time_zone,
                by_receipt_time=by_receipt_time,
                auto_parsing_mode=auto_parsing_mode
            )
        except PydanticValidationError as e:
            raise ValidationError(
                f"Search request validation failed: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"query": query, "from_time": from_time, "to_time": to_time}
            ) from e
        
        # Convert time parameters to proper ISO 8601 format for API
        try:
            from_time_formatted = TimeParser.convert_time_for_api(search_request.from_time)
            to_time_formatted = TimeParser.convert_time_for_api(search_request.to_time)
            
            # Additional validation to ensure from_time is before to_time
            from_dt = TimeParser.parse_time(search_request.from_time)
            to_dt = TimeParser.parse_time(search_request.to_time)
            
            if from_dt >= to_dt:
                raise TimeValidationError(
                    "Start time must be before end time",
                    f"from_time='{search_request.from_time}', to_time='{search_request.to_time}'",
                    "from_time should represent an earlier time than to_time (e.g., from='-2h', to='-1h')"
                )
            
        except TimeValidationError:
            # Re-raise TimeValidationError as-is
            raise
        except ValueError as e:
            raise TimeValidationError(
                f"Invalid time range: {str(e)}",
                f"from_time='{search_request.from_time}', to_time='{search_request.to_time}'",
                "Valid time formats: ISO 8601, relative time (-1h, -30m, now), or epoch time",
                context={"from_time": search_request.from_time, "to_time": search_request.to_time}
            ) from e
        
        # Prepare parameters for API schema validation
        search_params = {
            "query": search_request.query,
            "from": from_time_formatted,
            "to": to_time_formatted,
            "timeZone": search_request.time_zone,
            "byReceiptTime": search_request.by_receipt_time
        }
        
        if search_request.auto_parsing_mode:
            search_params["autoParsingMode"] = search_request.auto_parsing_mode
        
        # Validate parameters against official API schema
        try:
            validated_params = SumoLogicAPIValidator.validate_search_params(search_params)
        except (APIParameterError, TimeValidationError):
            # Re-raise enhanced validation errors as-is
            raise
        except (ValidationError, ValueError) as e:
            raise APIParameterError(
                param_name="search_params",
                param_value=search_params,
                expected_type="valid search parameters according to Sumo Logic API",
                api_endpoint="search API",
                context={"query": query, "from_time": from_time, "to_time": to_time, "original_error": str(e)}
            ) from e
        
        # Build search request payload with validated parameters
        search_payload = {
            "query": validated_params["query"],
            "from": validated_params["from"],
            "to": validated_params["to"],
            "timeZone": validated_params["timeZone"],
            "byReceiptTime": validated_params["byReceiptTime"]
        }
        
        if "autoParsingMode" in validated_params:
            search_payload["autoParsingMode"] = validated_params["autoParsingMode"]
        
        logger.info(
            "Starting log search",
            extra={
                "query": query[:100] + "..." if len(query) > 100 else query,
                "from_time": from_time,
                "to_time": to_time,
                "limit": limit
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint="/api/v1/search/jobs",
                json_data=search_payload,
                operation_type="search"
            )
            
            search_result = await self._parse_json_response(response)
            
            logger.info(
                "Search job created successfully",
                extra={
                    "job_id": search_result.get("id"),
                    "link": search_result.get("link")
                }
            )
            
            return search_result
            
        except APIError as e:
            raise SearchError(
                f"Failed to start search: {e.message}",
                query=query,
                context={"from_time": from_time, "to_time": to_time}
            ) from e
    
    async def get_search_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of running search job.
        
        Args:
            job_id: Search job ID
            
        Returns:
            Dictionary containing job status information
            
        Raises:
            APIParameterError: If job_id is invalid
            SearchError: If status check fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise APIParameterError(
                param_name="job_id",
                param_value=job_id,
                expected_type="non-empty string representing a valid search job ID",
                api_endpoint="search job status API"
            )
        
        job_id = job_id.strip()
        
        logger.debug(f"Checking status for search job {job_id}")
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v1/search/jobs/{job_id}",
                operation_type="search"
            )
            
            status_result = await self._parse_json_response(response)
            
            logger.debug(
                f"Search job status retrieved",
                extra={
                    "job_id": job_id,
                    "state": status_result.get("state"),
                    "message_count": status_result.get("messageCount"),
                    "record_count": status_result.get("recordCount")
                }
            )
            
            return status_result
            
        except APIError as e:
            raise SearchError(
                f"Failed to get search job status: {e.message}",
                job_id=job_id
            ) from e
    
    async def get_search_results(
        self,
        job_id: str,
        offset: int = 0,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Retrieve results from completed search job.
        
        Args:
            job_id: Search job ID
            offset: Result offset for pagination
            limit: Maximum results to return (1-10000)
            
        Returns:
            Dictionary containing search results
            
        Raises:
            APIParameterError: If parameters are invalid
            SearchError: If results retrieval fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise APIParameterError(
                param_name="job_id",
                param_value=job_id,
                expected_type="non-empty string representing a valid search job ID",
                api_endpoint="search results API"
            )
        
        if offset < 0:
            raise APIParameterError(
                param_name="offset",
                param_value=offset,
                expected_type="non-negative integer (>= 0)",
                api_endpoint="search results API"
            )
        
        if limit < 1 or limit > 10000:
            raise APIParameterError(
                param_name="limit",
                param_value=limit,
                expected_type="integer between 1 and 10000",
                api_endpoint="search results API"
            )
        
        job_id = job_id.strip()
        
        logger.debug(
            f"Retrieving results for search job {job_id}",
            extra={"offset": offset, "limit": limit}
        )
        
        try:
            # First check if job is complete
            status = await self.get_search_job_status(job_id)
            job_state = status.get("state", "").upper()
            
            if job_state not in ["DONE GATHERING RESULTS", "CANCELLED"]:
                raise SearchError(
                    f"Search job is not ready for results retrieval (state: {job_state})",
                    job_id=job_id,
                    search_state=job_state
                )
            
            # Get messages (log records)
            params = {
                "offset": offset,
                "limit": limit
            }
            
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v1/search/jobs/{job_id}/messages",
                params=params,
                operation_type="search_results"
            )
            
            results = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved search results",
                extra={
                    "job_id": job_id,
                    "returned_count": len(results.get("messages", [])),
                    "offset": offset,
                    "limit": limit
                }
            )
            
            # Combine with job status for complete result
            return {
                "job_id": job_id,
                "status": status,
                "results": results,
                "messages": results.get("messages", []),
                "fields": results.get("fields", [])
            }
            
        except SearchError:
            # Re-raise search errors as-is
            raise
        except APIError as e:
            raise SearchError(
                f"Failed to get search results: {e.message}",
                job_id=job_id
            ) from e
    
    async def cancel_search_job(self, job_id: str) -> bool:
        """Cancel a running search job.
        
        Args:
            job_id: Search job ID to cancel
            
        Returns:
            True if cancellation was successful
            
        Raises:
            APIParameterError: If job_id is invalid
            SearchError: If cancellation fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise APIParameterError(
                param_name="job_id",
                param_value=job_id,
                expected_type="non-empty string representing a valid search job ID",
                api_endpoint="search job cancellation API"
            )
        
        job_id = job_id.strip()
        
        logger.info(f"Cancelling search job {job_id}")
        
        try:
            response = await self._make_request(
                method="DELETE",
                endpoint=f"/api/v1/search/jobs/{job_id}",
                operation_type="search"
            )
            
            # Sumo Logic returns 200 for successful cancellation
            success = response.status_code == 200
            
            if success:
                logger.info(f"Search job {job_id} cancelled successfully")
            else:
                logger.warning(f"Search job {job_id} cancellation returned status {response.status_code}")
            
            return success
            
        except APIError as e:
            raise SearchError(
                f"Failed to cancel search job: {e.message}",
                job_id=job_id
            ) from e
    
    # Dashboard API Methods
    
    async def list_dashboards(
        self,
        limit: int = 100,
        offset: int = 0,
        filter_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """List available dashboards with optional filtering.
        
        Args:
            limit: Maximum dashboards to return (1-1000)
            offset: Result offset for pagination
            filter_query: Optional filter query (e.g., 'title:MyDashboard')
            
        Returns:
            Dictionary containing dashboard list and metadata
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        params = {
            "limit": limit,
            "offset": offset
        }
        
        if filter_query:
            params["q"] = filter_query.strip()
        
        logger.debug(
            "Listing dashboards",
            extra={"limit": limit, "offset": offset, "filter": filter_query}
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/api/v2/dashboards",
                params=params,
                operation_type="dashboard"
            )
            
            dashboards = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved {len(dashboards.get('data', []))} dashboards",
                extra={
                    "total_count": dashboards.get("totalCount"),
                    "limit": limit,
                    "offset": offset
                }
            )
            
            return dashboards
            
        except APIError as e:
            raise APIError(
                f"Failed to list dashboards: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id
            ) from e
    
    async def get_dashboard(self, dashboard_id: str) -> Dict[str, Any]:
        """Get specific dashboard configuration and metadata.
        
        Args:
            dashboard_id: Dashboard ID to retrieve
            
        Returns:
            Dictionary containing dashboard configuration
            
        Raises:
            APIParameterError: If dashboard_id is invalid
            APIError: If API request fails
        """
        if not dashboard_id or not dashboard_id.strip():
            raise APIParameterError(
                param_name="dashboard_id",
                param_value=dashboard_id,
                expected_type="non-empty string representing a valid dashboard ID",
                api_endpoint="dashboard retrieval API"
            )
        
        dashboard_id = dashboard_id.strip()
        
        logger.debug(f"Retrieving dashboard {dashboard_id}")
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v2/dashboards/{dashboard_id}",
                operation_type="dashboard"
            )
            
            dashboard = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved dashboard",
                extra={
                    "dashboard_id": dashboard_id,
                    "title": dashboard.get("title"),
                    "panel_count": len(dashboard.get("panels", []))
                }
            )
            
            return dashboard
            
        except APIError as e:
            raise APIError(
                f"Failed to get dashboard {dashboard_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"dashboard_id": dashboard_id}
            ) from e
    
    async def create_dashboard(self, dashboard_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create new dashboard with specified configuration.
        
        Args:
            dashboard_config: Dashboard configuration dictionary
            
        Returns:
            Dictionary containing created dashboard information
            
        Raises:
            ValidationError: If dashboard configuration is invalid
            APIError: If API request fails
        """
        # Validate dashboard configuration
        try:
            config = DashboardConfig(**dashboard_config)
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid dashboard configuration: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"config": dashboard_config}
            ) from e
        
        # Build dashboard payload
        dashboard_payload = {
            "title": config.title,
            "description": config.description or "",
            "panels": config.panels,
            "theme": getattr(config, 'theme', 'Light'),
            "timeRange": {
                "type": "BeginBoundedTimeRange",
                "from": {
                    "type": "RelativeTimeRangeBoundary",
                    "relativeTime": "-1h"
                }
            }
        }
        
        if config.refresh_interval:
            dashboard_payload["refreshInterval"] = config.refresh_interval
        
        if hasattr(config, 'folder_id') and config.folder_id:
            dashboard_payload["folderId"] = config.folder_id
        
        logger.info(
            f"Creating dashboard '{config.title}'",
            extra={
                "panel_count": len(config.panels),
                "has_description": bool(config.description)
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint="/api/v2/dashboards",
                json_data=dashboard_payload,
                operation_type="dashboard"
            )
            
            created_dashboard = await self._parse_json_response(response)
            
            logger.info(
                f"Dashboard created successfully",
                extra={
                    "dashboard_id": created_dashboard.get("id"),
                    "title": created_dashboard.get("title")
                }
            )
            
            return created_dashboard
            
        except APIError as e:
            raise APIError(
                f"Failed to create dashboard: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"title": config.title}
            ) from e
    
    async def update_dashboard(
        self,
        dashboard_id: str,
        dashboard_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update existing dashboard configuration.
        
        Args:
            dashboard_id: Dashboard ID to update
            dashboard_config: Updated dashboard configuration
            
        Returns:
            Dictionary containing updated dashboard information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if not dashboard_id or not dashboard_id.strip():
            raise ValidationError(
                "Dashboard ID cannot be empty",
                field_name="dashboard_id",
                field_value=dashboard_id
            )
        
        dashboard_id = dashboard_id.strip()
        
        # Get current dashboard to merge with updates
        try:
            current_dashboard = await self.get_dashboard(dashboard_id)
        except APIError as e:
            raise APIError(
                f"Failed to get current dashboard for update: {e.message}",
                status_code=e.status_code,
                context={"dashboard_id": dashboard_id}
            ) from e
        
        # Merge current config with updates
        updated_config = current_dashboard.copy()
        updated_config.update(dashboard_config)
        
        # Validate merged configuration
        try:
            config = DashboardConfig(
                title=updated_config.get("title", ""),
                description=updated_config.get("description"),
                panels=updated_config.get("panels", []),
                refresh_interval=updated_config.get("refreshInterval")
            )
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid updated dashboard configuration: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"dashboard_id": dashboard_id, "updates": dashboard_config}
            ) from e
        
        logger.info(
            f"Updating dashboard {dashboard_id}",
            extra={
                "title": config.title,
                "panel_count": len(config.panels)
            }
        )
        
        try:
            response = await self._make_request(
                method="PUT",
                endpoint=f"/api/v2/dashboards/{dashboard_id}",
                json_data=updated_config,
                operation_type="dashboard"
            )
            
            updated_dashboard = await self._parse_json_response(response)
            
            logger.info(
                f"Dashboard updated successfully",
                extra={
                    "dashboard_id": dashboard_id,
                    "title": updated_dashboard.get("title")
                }
            )
            
            return updated_dashboard
            
        except APIError as e:
            raise APIError(
                f"Failed to update dashboard {dashboard_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"dashboard_id": dashboard_id}
            ) from e
    
    async def delete_dashboard(self, dashboard_id: str) -> bool:
        """Delete specified dashboard.
        
        Args:
            dashboard_id: Dashboard ID to delete
            
        Returns:
            True if deletion was successful
            
        Raises:
            ValidationError: If dashboard_id is invalid
            APIError: If API request fails
        """
        if not dashboard_id or not dashboard_id.strip():
            raise ValidationError(
                "Dashboard ID cannot be empty",
                field_name="dashboard_id",
                field_value=dashboard_id
            )
        
        dashboard_id = dashboard_id.strip()
        
        logger.info(f"Deleting dashboard {dashboard_id}")
        
        try:
            response = await self._make_request(
                method="DELETE",
                endpoint=f"/api/v2/dashboards/{dashboard_id}",
                operation_type="dashboard"
            )
            
            # Sumo Logic returns 204 for successful deletion
            success = response.status_code == 204
            
            if success:
                logger.info(f"Dashboard {dashboard_id} deleted successfully")
            else:
                logger.warning(f"Dashboard {dashboard_id} deletion returned status {response.status_code}")
            
            return success
            
        except APIError as e:
            raise APIError(
                f"Failed to delete dashboard {dashboard_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"dashboard_id": dashboard_id}
            ) from e
    
    # Metrics API Methods
    
    async def query_metrics(
        self,
        query: str,
        from_time: str,
        to_time: str,
        requested_data_points: int = 600,
        max_tab_results: int = 100
    ) -> Dict[str, Any]:
        """Execute metrics query for time-series data retrieval.
        
        Args:
            query: Metrics query string
            from_time: Start time (ISO format or relative like '-1h')
            to_time: End time (ISO format or relative like 'now')
            requested_data_points: Number of data points to return (1-1440)
            max_tab_results: Maximum tabular results (1-1000)
            
        Returns:
            Dictionary containing metrics query results
            
        Raises:
            ValidationError: If query parameters are invalid
            APIError: If API request fails
        """
        # Validate metrics request
        try:
            metrics_request = MetricsRequest(
                query=query,
                from_time=from_time,
                to_time=to_time,
                requested_data_points=requested_data_points,
                max_tab_results=max_tab_results
            )
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid metrics query parameters: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"query": query, "from_time": from_time, "to_time": to_time}
            ) from e
        
        # Parse and validate time range with enhanced time handling
        try:
            # First validate the time range
            start_dt, end_dt = TimeParser.validate_time_range(
                metrics_request.from_time, 
                metrics_request.to_time
            )
            
            # For metrics API, we can use relative time if it's in the original format
            # or convert to epoch milliseconds
            if TimeParser._is_relative_time(metrics_request.from_time) or metrics_request.from_time.lower() == 'now':
                from_time_value = metrics_request.from_time
                from_time_type = "RelativeTimeRangeBoundary"
                from_time_key = "relativeTime"
            else:
                from_time_value = str(int(start_dt.timestamp() * 1000))
                from_time_type = "EpochTimeRangeBoundary"
                from_time_key = "epochMillis"
            
            if TimeParser._is_relative_time(metrics_request.to_time) or metrics_request.to_time.lower() == 'now':
                to_time_value = metrics_request.to_time
                to_time_type = "RelativeTimeRangeBoundary"
                to_time_key = "relativeTime"
            else:
                to_time_value = str(int(end_dt.timestamp() * 1000))
                to_time_type = "EpochTimeRangeBoundary"
                to_time_key = "epochMillis"
                
        except ValueError as e:
            raise ValidationError(
                f"Invalid time range for metrics query: {e}",
                field_name="time_range",
                context={"from_time": metrics_request.from_time, "to_time": metrics_request.to_time}
            ) from e
        
        # Build metrics query payload
        metrics_payload = {
            "query": [
                {
                    "query": metrics_request.query,
                    "rowId": "A"
                }
            ],
            "timeRange": {
                "type": "BeginBoundedTimeRange",
                "from": {
                    "type": from_time_type,
                    from_time_key: from_time_value
                },
                "to": {
                    "type": to_time_type,
                    to_time_key: to_time_value
                }
            },
            "requestedDataPoints": metrics_request.requested_data_points,
            "maxTabResults": metrics_request.max_tab_results
        }
        
        logger.info(
            "Executing metrics query",
            extra={
                "query": query[:100] + "..." if len(query) > 100 else query,
                "from_time": from_time,
                "to_time": to_time,
                "data_points": requested_data_points
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint="/api/v1/metrics/results",
                json_data=metrics_payload,
                operation_type="metrics"
            )
            
            metrics_result = await self._parse_json_response(response)
            
            logger.info(
                "Metrics query completed successfully",
                extra={
                    "query_count": len(metrics_result.get("queryResult", [])),
                    "has_tabular_data": bool(metrics_result.get("tabularData"))
                }
            )
            
            return metrics_result
            
        except APIError as e:
            raise APIError(
                f"Failed to execute metrics query: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"query": query, "from_time": from_time, "to_time": to_time}
            ) from e
    
    async def list_metric_sources(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List available metric sources for discovery.
        
        Args:
            limit: Maximum sources to return (1-1000)
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing metric sources list
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        params = {
            "limit": limit,
            "offset": offset
        }
        
        logger.debug(
            "Listing metric sources",
            extra={"limit": limit, "offset": offset}
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/api/v1/metrics/sources",
                params=params,
                operation_type="metrics"
            )
            
            sources = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved {len(sources.get('data', []))} metric sources",
                extra={
                    "total_count": sources.get("totalCount"),
                    "limit": limit,
                    "offset": offset
                }
            )
            
            return sources
            
        except APIError as e:
            raise APIError(
                f"Failed to list metric sources: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id
            ) from e
    
    async def get_metric_metadata(
        self,
        metric_name: str,
        source_host: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get metadata for a specific metric.
        
        Args:
            metric_name: Name of the metric to get metadata for
            source_host: Optional source host filter
            
        Returns:
            Dictionary containing metric metadata
            
        Raises:
            ValidationError: If metric_name is invalid
            APIError: If API request fails
        """
        if not metric_name or not metric_name.strip():
            raise ValidationError(
                "Metric name cannot be empty",
                field_name="metric_name",
                field_value=metric_name
            )
        
        metric_name = metric_name.strip()
        
        params = {"metric": metric_name}
        if source_host:
            params["sourceHost"] = source_host.strip()
        
        logger.debug(
            f"Getting metadata for metric '{metric_name}'",
            extra={"source_host": source_host}
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/api/v1/metrics/metadata",
                params=params,
                operation_type="metrics"
            )
            
            metadata = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved metadata for metric '{metric_name}'",
                extra={
                    "metric_name": metric_name,
                    "dimensions_count": len(metadata.get("dimensions", []))
                }
            )
            
            return metadata
            
        except APIError as e:
            raise APIError(
                f"Failed to get metric metadata for '{metric_name}': {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"metric_name": metric_name, "source_host": source_host}
            ) from e
    
    # Collector and Source API Methods
    
    async def list_collectors(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List collectors with pagination.
        
        Args:
            limit: Maximum collectors to return (1-1000)
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing collectors list and metadata
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        params = {
            "limit": limit,
            "offset": offset
        }
        
        logger.debug(
            "Listing collectors",
            extra={"limit": limit, "offset": offset}
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/api/v1/collectors",
                params=params,
                operation_type="collector"
            )
            
            collectors = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved {len(collectors.get('collectors', []))} collectors",
                extra={
                    "limit": limit,
                    "offset": offset
                }
            )
            
            return collectors
            
        except APIError as e:
            raise APIError(
                f"Failed to list collectors: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id
            ) from e
    
    async def get_collector(self, collector_id: Union[str, int]) -> Dict[str, Any]:
        """Get collector details and configuration.
        
        Args:
            collector_id: Collector ID (string or integer)
            
        Returns:
            Dictionary containing collector information
            
        Raises:
            ValidationError: If collector_id is invalid
            APIError: If API request fails
        """
        if not collector_id:
            raise ValidationError(
                "Collector ID cannot be empty",
                field_name="collector_id",
                field_value=collector_id
            )
        
        # Convert to string and validate
        collector_id_str = str(collector_id).strip()
        if not collector_id_str:
            raise ValidationError(
                "Collector ID cannot be empty after conversion",
                field_name="collector_id",
                field_value=collector_id
            )
        
        logger.debug(f"Retrieving collector {collector_id_str}")
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v1/collectors/{collector_id_str}",
                operation_type="collector"
            )
            
            collector = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved collector",
                extra={
                    "collector_id": collector_id_str,
                    "name": collector.get("collector", {}).get("name"),
                    "collector_type": collector.get("collector", {}).get("collectorType")
                }
            )
            
            return collector
            
        except APIError as e:
            raise APIError(
                f"Failed to get collector {collector_id_str}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"collector_id": collector_id_str}
            ) from e
    
    async def create_collector(self, collector_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create new collector with specified configuration.
        
        Args:
            collector_config: Collector configuration dictionary
            
        Returns:
            Dictionary containing created collector information
            
        Raises:
            ValidationError: If collector configuration is invalid
            APIError: If API request fails
        """
        # Validate collector configuration
        try:
            config = CollectorConfig(**collector_config)
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid collector configuration: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"config": collector_config}
            ) from e
        
        # Build collector payload
        collector_payload = {
            "collector": {
                "collectorType": "Hosted",  # Default to hosted collector
                "name": config.name,
                "description": config.description or "",
                "category": config.category,
                "hostName": config.host_name,
                "timeZone": config.time_zone,
                "ephemeral": config.ephemeral,
                "sourceSyncMode": config.source_sync_mode
            }
        }
        
        logger.info(
            f"Creating collector '{config.name}'",
            extra={
                "collector_type": "Hosted",
                "ephemeral": config.ephemeral
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint="/api/v1/collectors",
                json_data=collector_payload,
                operation_type="collector"
            )
            
            created_collector = await self._parse_json_response(response)
            
            logger.info(
                f"Collector created successfully",
                extra={
                    "collector_id": created_collector.get("collector", {}).get("id"),
                    "name": created_collector.get("collector", {}).get("name")
                }
            )
            
            return created_collector
            
        except APIError as e:
            raise APIError(
                f"Failed to create collector: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"name": config.name}
            ) from e
    
    async def update_collector(
        self,
        collector_id: Union[str, int],
        collector_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update collector configuration.
        
        Args:
            collector_id: Collector ID to update
            collector_config: Updated collector configuration
            
        Returns:
            Dictionary containing updated collector information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if not collector_id:
            raise ValidationError(
                "Collector ID cannot be empty",
                field_name="collector_id",
                field_value=collector_id
            )
        
        collector_id_str = str(collector_id).strip()
        
        # Get current collector to merge with updates
        try:
            current_collector = await self.get_collector(collector_id_str)
            current_config = current_collector.get("collector", {})
        except APIError as e:
            raise APIError(
                f"Failed to get current collector for update: {e.message}",
                status_code=e.status_code,
                context={"collector_id": collector_id_str}
            ) from e
        
        # Merge current config with updates
        updated_config = current_config.copy()
        updated_config.update(collector_config)
        
        # Validate merged configuration
        try:
            config = CollectorConfig(
                name=updated_config.get("name", ""),
                description=updated_config.get("description"),
                category=updated_config.get("category"),
                host_name=updated_config.get("hostName"),
                time_zone=updated_config.get("timeZone", "UTC"),
                ephemeral=updated_config.get("ephemeral", True),
                source_sync_mode=updated_config.get("sourceSyncMode", "UI")
            )
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid updated collector configuration: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"collector_id": collector_id_str, "updates": collector_config}
            ) from e
        
        # Build update payload
        update_payload = {
            "collector": updated_config
        }
        
        logger.info(
            f"Updating collector {collector_id_str}",
            extra={"collector_name": config.name}
        )
        
        try:
            response = await self._make_request(
                method="PUT",
                endpoint=f"/api/v1/collectors/{collector_id_str}",
                json_data=update_payload,
                operation_type="collector"
            )
            
            updated_collector = await self._parse_json_response(response)
            
            logger.info(
                f"Collector updated successfully",
                extra={
                    "collector_id": collector_id_str,
                    "name": updated_collector.get("collector", {}).get("name")
                }
            )
            
            return updated_collector
            
        except APIError as e:
            raise APIError(
                f"Failed to update collector {collector_id_str}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"collector_id": collector_id_str}
            ) from e
    
    async def delete_collector(self, collector_id: Union[str, int]) -> bool:
        """Delete specified collector.
        
        Args:
            collector_id: Collector ID to delete
            
        Returns:
            True if deletion was successful
            
        Raises:
            ValidationError: If collector_id is invalid
            APIError: If API request fails
        """
        if not collector_id:
            raise ValidationError(
                "Collector ID cannot be empty",
                field_name="collector_id",
                field_value=collector_id
            )
        
        collector_id_str = str(collector_id).strip()
        
        logger.info(f"Deleting collector {collector_id_str}")
        
        try:
            response = await self._make_request(
                method="DELETE",
                endpoint=f"/api/v1/collectors/{collector_id_str}",
                operation_type="collector"
            )
            
            # Sumo Logic returns 200 for successful deletion
            success = response.status_code == 200
            
            if success:
                logger.info(f"Collector {collector_id_str} deleted successfully")
            else:
                logger.warning(f"Collector {collector_id_str} deletion returned status {response.status_code}")
            
            return success
            
        except APIError as e:
            raise APIError(
                f"Failed to delete collector {collector_id_str}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"collector_id": collector_id_str}
            ) from e
    
    async def list_sources(
        self,
        collector_id: Union[str, int],
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List sources for specified collector.
        
        Args:
            collector_id: Collector ID to list sources for
            limit: Maximum sources to return (1-1000)
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing sources list and metadata
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if not collector_id:
            raise ValidationError(
                "Collector ID cannot be empty",
                field_name="collector_id",
                field_value=collector_id
            )
        
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        collector_id_str = str(collector_id).strip()
        
        params = {
            "limit": limit,
            "offset": offset
        }
        
        logger.debug(
            f"Listing sources for collector {collector_id_str}",
            extra={"limit": limit, "offset": offset}
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v1/collectors/{collector_id_str}/sources",
                params=params,
                operation_type="collector"
            )
            
            sources = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved {len(sources.get('sources', []))} sources for collector {collector_id_str}",
                extra={
                    "collector_id": collector_id_str,
                    "limit": limit,
                    "offset": offset
                }
            )
            
            return sources
            
        except APIError as e:
            raise APIError(
                f"Failed to list sources for collector {collector_id_str}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"collector_id": collector_id_str}
            ) from e
    
    async def create_source(
        self,
        collector_id: Union[str, int],
        source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create new source in specified collector.
        
        Args:
            collector_id: Collector ID to create source in
            source_config: Source configuration dictionary
            
        Returns:
            Dictionary containing created source information
            
        Raises:
            ValidationError: If configuration is invalid
            APIError: If API request fails
        """
        if not collector_id:
            raise ValidationError(
                "Collector ID cannot be empty",
                field_name="collector_id",
                field_value=collector_id
            )
        
        collector_id_str = str(collector_id).strip()
        
        # Validate source configuration
        try:
            config = SourceConfig(**source_config)
        except PydanticValidationError as e:
            raise ValidationError(
                f"Invalid source configuration: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"collector_id": collector_id_str, "config": source_config}
            ) from e
        
        # Build source payload
        source_payload = {
            "source": {
                "sourceType": source_config.get("sourceType", "HTTP"),  # Default to HTTP source
                "name": config.name,
                "description": config.description or "",
                "category": config.category,
                "hostName": config.host_name,
                "timeZone": config.time_zone,
                "automaticDateParsing": config.automatic_date_parsing,
                "multilineProcessingEnabled": config.multiline_processing_enabled,
                "useAutolineMatching": config.use_autoline_matching,
                "forceTimeZone": config.force_time_zone
            }
        }
        
        if config.default_date_format:
            source_payload["source"]["defaultDateFormat"] = config.default_date_format
        
        if config.filters:
            source_payload["source"]["filters"] = config.filters
        
        logger.info(
            f"Creating source '{config.name}' in collector {collector_id_str}",
            extra={
                "collector_id": collector_id_str,
                "source_type": source_config.get("sourceType", "HTTP")
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint=f"/api/v1/collectors/{collector_id_str}/sources",
                json_data=source_payload,
                operation_type="collector"
            )
            
            created_source = await self._parse_json_response(response)
            
            logger.info(
                f"Source created successfully",
                extra={
                    "collector_id": collector_id_str,
                    "source_id": created_source.get("source", {}).get("id"),
                    "name": created_source.get("source", {}).get("name")
                }
            )
            
            return created_source
            
        except APIError as e:
            raise APIError(
                f"Failed to create source in collector {collector_id_str}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"collector_id": collector_id_str, "name": config.name}
            ) from e

    # Monitor API Methods
    
    async def list_monitors(
        self,
        limit: int = 100,
        offset: int = 0,
        filter_name: Optional[str] = None,
        filter_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        content_type: Optional[str] = None,
        include_folders: bool = True
    ) -> Dict[str, Any]:
        """List monitors with optional filtering and pagination, including folder-based searches.
        
        Args:
            limit: Maximum monitors to return (1-1000)
            offset: Result offset for pagination
            filter_name: Optional name filter (partial match)
            filter_type: Optional monitor type filter
            filter_status: Optional status filter (enabled, disabled, triggered)
            content_type: Optional content type filter (MonitorsLibraryMonitor, MonitorsLibraryFolder, *)
            include_folders: Whether to include monitors within folders (default: True)
            
        Returns:
            Dictionary containing monitor list and metadata with folder information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        # Build filter query - the search endpoint requires a query parameter
        filter_parts = []
        if filter_name:
            filter_parts.append(f'name:"{filter_name.strip()}"')
        if filter_type:
            filter_parts.append(f'monitorType:"{filter_type.strip()}"')
        if filter_status:
            # Map common status terms to Sumo Logic format
            status_mapping = {
                "enabled": "isDisabled:false",
                "disabled": "isDisabled:true",
                "triggered": "status:Triggered"
            }
            mapped_status = status_mapping.get(filter_status.lower(), f'status:"{filter_status}"')
            filter_parts.append(mapped_status)
        
        # Always provide a query parameter - use "*" for all if no filters
        if filter_parts:
            query = " AND ".join(filter_parts)
        else:
            query = "*"  # Search for all monitors
        
        # Determine content type for folder inclusion
        if content_type:
            # Use explicitly provided content type
            search_content_type = content_type
        elif include_folders:
            # Default to searching all content types including folders
            search_content_type = "*"
        else:
            # Only search monitors, not folders
            search_content_type = "MonitorsLibraryMonitor"
        
        # Prepare parameters for validation
        monitor_params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "type": search_content_type
        }
        
        # Validate parameters against official API schema
        try:
            validated_params = SumoLogicAPIValidator.validate_monitor_params(monitor_params)
        except (ValidationError, ValueError) as e:
            raise ValidationError(
                f"Monitor parameter validation failed: {e}",
                context={"limit": limit, "offset": offset, "query": query}
            ) from e
        
        logger.debug(
            "Listing monitors",
            extra={
                "limit": validated_params["limit"],
                "offset": validated_params["offset"],
                "query": validated_params["query"],
                "filters": {
                    "name": filter_name,
                    "type": filter_type,
                    "status": filter_status,
                    "content_type": content_type
                }
            }
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/api/v1/monitors/search",
                params=validated_params,
                operation_type="monitor"
            )
            
            monitors = await self._parse_json_response(response)
            
            # Handle both list and dict responses
            if isinstance(monitors, list):
                # Direct list response from search endpoint
                monitor_list = monitors
                total_count = len(monitors)
            else:
                # Dict response with data key
                monitor_list = monitors.get('data', [])
                total_count = monitors.get("totalCount", len(monitor_list))
            
            # Process folder information and perform recursive search if needed
            processed_monitors = []
            folder_count = 0
            
            for item in monitor_list:
                # Check if this is a folder
                if item.get("contentType") == "MonitorsLibraryFolder":
                    folder_count += 1
                    # Add folder path information
                    item["folder_path"] = self._extract_folder_path(item)
                    
                    # If include_folders is True and we're searching all content types,
                    # perform recursive search within this folder
                    if include_folders and search_content_type == "*":
                        try:
                            folder_monitors = await self._search_monitors_in_folder(
                                item.get("id"), query, limit, offset
                            )
                            # Add folder path to nested monitors
                            for folder_monitor in folder_monitors:
                                folder_monitor["folder_path"] = item["folder_path"]
                                folder_monitor["parent_folder_id"] = item.get("id")
                            processed_monitors.extend(folder_monitors)
                        except Exception as e:
                            logger.warning(
                                f"Failed to search monitors in folder {item.get('name', 'unknown')}: {e}",
                                extra={"folder_id": item.get("id"), "error": str(e)}
                            )
                
                # Add monitor/folder to results with folder information
                if item.get("contentType") == "MonitorsLibraryMonitor":
                    item["folder_path"] = self._extract_folder_path(item)
                
                processed_monitors.append(item)
            
            logger.info(
                f"Retrieved {len(processed_monitors)} items ({len(processed_monitors) - folder_count} monitors, {folder_count} folders)",
                extra={
                    "total_count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "include_folders": include_folders,
                    "content_type": search_content_type
                }
            )
            
            # Return in expected format with folder metadata
            return {
                "data": processed_monitors,
                "total": total_count,
                "totalCount": total_count,
                "limit": validated_params["limit"],
                "offset": validated_params["offset"],
                "folder_info": {
                    "folders_found": folder_count,
                    "monitors_found": len(processed_monitors) - folder_count,
                    "include_folders": include_folders,
                    "content_type_filter": search_content_type
                }
            }
            
        except APIError as e:
            raise APIError(
                f"Failed to list monitors: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id
            ) from e
    
    def _extract_folder_path(self, item: Dict[str, Any]) -> str:
        """Extract folder path from monitor or folder item.
        
        Args:
            item: Monitor or folder item from API response
            
        Returns:
            Folder path string (e.g., "/Monitors/Production/Alerts")
        """
        # Try to get path from various possible fields
        path_fields = ["path", "parentPath", "folderPath"]
        
        for field in path_fields:
            if field in item and item[field]:
                return item[field]
        
        # If no explicit path, try to construct from name and parent info
        name = item.get("name", "")
        parent_id = item.get("parentId")
        
        if parent_id:
            # This item is in a folder, but we don't have the full path
            # Return a partial path indication
            return f"/.../{name}"
        
        # Root level item
        return f"/{name}" if name else "/unknown"
    
    async def _search_monitors_in_folder(
        self,
        folder_id: str,
        base_query: str,
        limit: int,
        offset: int
    ) -> List[Dict[str, Any]]:
        """Search for monitors within a specific folder.
        
        Args:
            folder_id: ID of the folder to search in
            base_query: Base search query to apply
            limit: Maximum results to return
            offset: Result offset
            
        Returns:
            List of monitors found in the folder
        """
        try:
            # Build query to search within specific folder
            folder_query = f"parentId:{folder_id}"
            if base_query and base_query != "*":
                folder_query = f"({base_query}) AND {folder_query}"
            
            folder_params = {
                "query": folder_query,
                "limit": limit,
                "offset": offset,
                "type": "MonitorsLibraryMonitor"  # Only search for monitors in folders
            }
            
            # Validate parameters
            validated_folder_params = SumoLogicAPIValidator.validate_monitor_params(folder_params)
            
            response = await self._make_request(
                method="GET",
                endpoint="/api/v1/monitors/search",
                params=validated_folder_params,
                operation_type="monitor"
            )
            
            folder_monitors = await self._parse_json_response(response)
            
            # Handle response format
            if isinstance(folder_monitors, list):
                return folder_monitors
            else:
                return folder_monitors.get('data', [])
                
        except Exception as e:
            logger.warning(
                f"Failed to search monitors in folder {folder_id}: {e}",
                extra={"folder_id": folder_id, "error": str(e)}
            )
            return []
    
    async def get_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Get specific monitor configuration and details.
        
        Args:
            monitor_id: Monitor ID to retrieve
            
        Returns:
            Dictionary containing monitor configuration
            
        Raises:
            ValidationError: If monitor_id is invalid
            APIError: If API request fails
        """
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        logger.debug(f"Retrieving monitor {monitor_id}")
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"/api/v1/monitors/{monitor_id}",
                operation_type="monitor"
            )
            
            monitor = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved monitor",
                extra={
                    "monitor_id": monitor_id,
                    "name": monitor.get("name"),
                    "type": monitor.get("monitorType"),
                    "is_disabled": monitor.get("isDisabled")
                }
            )
            
            return monitor
            
        except APIError as e:
            raise APIError(
                f"Failed to get monitor {monitor_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e
    
    async def create_monitor(self, monitor_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create new monitor with specified configuration.
        
        Args:
            monitor_config: Monitor configuration dictionary
            
        Returns:
            Dictionary containing created monitor information
            
        Raises:
            ValidationError: If monitor configuration is invalid
            APIError: If API request fails
        """
        from .models.monitor import MonitorConfig
        
        # Validate monitor configuration
        try:
            config = MonitorConfig(**monitor_config)
        except Exception as e:
            raise ValidationError(
                f"Invalid monitor configuration: {e}",
                context={"config": monitor_config}
            ) from e
        
        # Build monitor payload for Sumo Logic API
        monitor_payload = {
            "name": config.name,
            "description": config.description or "",
            "type": config.type.value,
            "isDisabled": config.is_disabled,
            "contentType": "Monitor",
            "queries": [
                {
                    "rowId": "A",
                    "query": config.query
                }
            ],
            "triggers": [],
            "notifications": []
        }
        
        # Convert trigger conditions to Sumo Logic format
        for trigger_type, condition in config.trigger_conditions.items():
            trigger_payload = {
                "triggerType": trigger_type.value,
                "threshold": condition.threshold,
                "thresholdType": condition.threshold_type.value,
                "timeRange": condition.time_range,
                "occurrenceType": condition.occurrence_type.value,
                "triggerSource": condition.trigger_source.value
            }
            monitor_payload["triggers"].append(trigger_payload)
        
        # Convert notifications to Sumo Logic format
        for notification in config.notifications:
            notification_payload = {
                "notification": {
                    "actionType": notification.action_type.value
                }
            }
            
            if notification.subject:
                notification_payload["notification"]["subject"] = notification.subject
            if notification.message_body:
                notification_payload["notification"]["messageBody"] = notification.message_body
            if notification.recipients:
                notification_payload["notification"]["recipients"] = notification.recipients
            if notification.webhook_url:
                notification_payload["notification"]["connectionId"] = notification.webhook_url
            
            monitor_payload["notifications"].append(notification_payload)
        
        # Add optional fields
        if config.evaluation_delay and config.evaluation_delay != "0m":
            monitor_payload["evaluationDelay"] = config.evaluation_delay
        
        monitor_payload["groupNotifications"] = config.group_notifications
        
        logger.info(
            f"Creating monitor '{config.name}'",
            extra={
                "type": config.type.value,
                "trigger_count": len(config.trigger_conditions),
                "notification_count": len(config.notifications)
            }
        )
        
        try:
            response = await self._make_request(
                method="POST",
                endpoint="/api/v1/monitors",
                json_data=monitor_payload,
                operation_type="monitor"
            )
            
            created_monitor = await self._parse_json_response(response)
            
            logger.info(
                f"Monitor created successfully",
                extra={
                    "monitor_id": created_monitor.get("id"),
                    "name": created_monitor.get("name")
                }
            )
            
            return created_monitor
            
        except APIError as e:
            raise APIError(
                f"Failed to create monitor: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"name": config.name}
            ) from e
    
    async def update_monitor(
        self,
        monitor_id: str,
        monitor_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update existing monitor configuration.
        
        Args:
            monitor_id: Monitor ID to update
            monitor_config: Updated monitor configuration (partial updates supported)
            
        Returns:
            Dictionary containing updated monitor information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        # Get current monitor to merge with updates
        try:
            current_monitor = await self.get_monitor(monitor_id)
        except APIError as e:
            raise APIError(
                f"Failed to get current monitor for update: {e.message}",
                status_code=e.status_code,
                context={"monitor_id": monitor_id}
            ) from e
        
        # Merge current config with updates
        updated_config = current_monitor.copy()
        
        # Handle partial updates carefully
        for key, value in monitor_config.items():
            if key in ["trigger_conditions", "notifications"]:
                # For complex objects, replace entirely if provided
                updated_config[key] = value
            else:
                updated_config[key] = value
        
        logger.info(
            f"Updating monitor {monitor_id}",
            extra={
                "name": updated_config.get("name"),
                "update_fields": list(monitor_config.keys())
            }
        )
        
        try:
            response = await self._make_request(
                method="PUT",
                endpoint=f"/api/v1/monitors/{monitor_id}",
                json_data=updated_config,
                operation_type="monitor"
            )
            
            updated_monitor = await self._parse_json_response(response)
            
            logger.info(
                f"Monitor updated successfully",
                extra={
                    "monitor_id": monitor_id,
                    "name": updated_monitor.get("name")
                }
            )
            
            return updated_monitor
            
        except APIError as e:
            raise APIError(
                f"Failed to update monitor {monitor_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e
    
    async def delete_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Delete specified monitor.
        
        Args:
            monitor_id: Monitor ID to delete
            
        Returns:
            Dictionary containing deletion confirmation and deleted monitor info
            
        Raises:
            ValidationError: If monitor_id is invalid
            APIError: If API request fails
        """
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        # Get monitor details before deletion for confirmation
        try:
            monitor_info = await self.get_monitor(monitor_id)
        except APIError as e:
            # If monitor doesn't exist, still try deletion to get proper error
            monitor_info = {"id": monitor_id, "name": "Unknown"}
        
        logger.info(f"Deleting monitor {monitor_id}")
        
        try:
            response = await self._make_request(
                method="DELETE",
                endpoint=f"/api/v1/monitors/{monitor_id}",
                operation_type="monitor"
            )
            
            # Sumo Logic returns 204 for successful deletion
            success = response.status_code == 204
            
            if success:
                logger.info(f"Monitor {monitor_id} deleted successfully")
                return {
                    "success": True,
                    "message": f"Monitor '{monitor_info.get('name', monitor_id)}' deleted successfully",
                    "deleted_monitor": {
                        "id": monitor_id,
                        "name": monitor_info.get("name"),
                        "type": monitor_info.get("monitorType")
                    }
                }
            else:
                logger.warning(f"Monitor {monitor_id} deletion returned status {response.status_code}")
                return {
                    "success": False,
                    "message": f"Monitor deletion returned unexpected status {response.status_code}",
                    "monitor_id": monitor_id
                }
            
        except APIError as e:
            raise APIError(
                f"Failed to delete monitor {monitor_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e
    
    async def get_monitor_status(
        self,
        monitor_id: Optional[str] = None,
        filter_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get monitor status information.
        
        Args:
            monitor_id: Optional specific monitor ID to get status for
            filter_status: Optional status filter (triggered, normal, disabled)
            limit: Maximum results to return (1-1000)
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing monitor status information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        # Build endpoint and parameters
        if monitor_id:
            if not monitor_id.strip():
                raise ValidationError(
                    "Monitor ID cannot be empty",
                    field_name="monitor_id",
                    field_value=monitor_id
                )
            monitor_id = monitor_id.strip()
            endpoint = f"/api/v1/monitors/{monitor_id}/status"
            params = {}
        else:
            endpoint = "/api/v1/monitors/status"
            params = {
                "limit": limit,
                "offset": offset
            }
            
            if filter_status:
                params["status"] = filter_status.strip()
        
        logger.debug(
            "Getting monitor status",
            extra={
                "monitor_id": monitor_id,
                "filter_status": filter_status,
                "limit": limit if not monitor_id else None
            }
        )
        
        try:
            response = await self._make_request(
                method="GET",
                endpoint=endpoint,
                params=params,
                operation_type="monitor"
            )
            
            status_result = await self._parse_json_response(response)
            
            logger.info(
                f"Retrieved monitor status",
                extra={
                    "monitor_id": monitor_id,
                    "status_count": len(status_result.get("data", [])) if not monitor_id else 1
                }
            )
            
            return status_result
            
        except APIError as e:
            raise APIError(
                f"Failed to get monitor status: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e
    
    async def enable_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Enable a disabled monitor.
        
        Args:
            monitor_id: Monitor ID to enable
            
        Returns:
            Dictionary containing enable operation result
            
        Raises:
            ValidationError: If monitor_id is invalid
            APIError: If API request fails
        """
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        logger.info(f"Enabling monitor {monitor_id}")
        
        try:
            # Update monitor to set isDisabled = false
            response = await self._make_request(
                method="PUT",
                endpoint=f"/api/v1/monitors/{monitor_id}/disable",
                json_data={"isDisabled": False},
                operation_type="monitor"
            )
            
            result = await self._parse_json_response(response)
            
            logger.info(f"Monitor {monitor_id} enabled successfully")
            
            return {
                "success": True,
                "message": f"Monitor {monitor_id} enabled successfully",
                "monitor_id": monitor_id,
                "status": "enabled",
                "timestamp": result.get("modifiedAt")
            }
            
        except APIError as e:
            raise APIError(
                f"Failed to enable monitor {monitor_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e
    
    async def disable_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Disable an enabled monitor.
        
        Args:
            monitor_id: Monitor ID to disable
            
        Returns:
            Dictionary containing disable operation result
            
        Raises:
            ValidationError: If monitor_id is invalid
            APIError: If API request fails
        """
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        logger.info(f"Disabling monitor {monitor_id}")
        
        try:
            # Update monitor to set isDisabled = true
            response = await self._make_request(
                method="PUT",
                endpoint=f"/api/v1/monitors/{monitor_id}/disable",
                json_data={"isDisabled": True},
                operation_type="monitor"
            )
            
            result = await self._parse_json_response(response)
            
            logger.info(f"Monitor {monitor_id} disabled successfully")
            
            return {
                "success": True,
                "message": f"Monitor {monitor_id} disabled successfully",
                "monitor_id": monitor_id,
                "status": "disabled",
                "timestamp": result.get("modifiedAt")
            }
            
        except APIError as e:
            raise APIError(
                f"Failed to disable monitor {monitor_id}: {e.message}",
                status_code=e.status_code,
                response_body=e.response_body,
                request_id=e.request_id,
                context={"monitor_id": monitor_id}
            ) from e

    async def get_active_alerts(
        self,
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get all currently active alerts with optional severity filtering.
        
        This method uses progressive endpoint fallback to find working API endpoints
        for retrieving active alerts, addressing the 400 error from incorrect endpoints.
        
        Args:
            severity: Optional severity filter (Critical, Warning, MissingData)
            limit: Maximum results to return (1-1000)
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing active alerts information
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails after all fallback attempts
        """
        # Enhanced parameter validation
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        # Validate and normalize severity if provided
        if severity:
            severity = severity.strip()
            valid_severities = ["Critical", "Warning", "MissingData"]
            if severity not in valid_severities:
                raise ValidationError(
                    f"Invalid severity '{severity}'. Must be one of: {', '.join(valid_severities)}",
                    field_name="severity",
                    field_value=severity,
                    context={"valid_options": valid_severities}
                )
        
        # Check circuit breaker status before attempting requests
        if self.is_circuit_breaker_open():
            logger.warning(
                "Circuit breaker is open - attempting reset before proceeding",
                extra={
                    "severity": severity,
                    "limit": limit,
                    "offset": offset
                }
            )
            
            # Try to reset circuit breaker
            reset_result = await self.reset_circuit_breaker()
            if not reset_result.get("reset_successful"):
                # If reset fails, provide graceful degradation
                return {
                    "data": [],
                    "total": 0,
                    "totalCount": 0,
                    "endpoint_used": "circuit_breaker_fallback",
                    "endpoint_name": "circuit_breaker_open",
                    "severity_filter": severity,
                    "metadata": {
                        "source_endpoint": "circuit_breaker_fallback",
                        "processing_method": "circuit_breaker_open_degradation",
                        "degradation_reason": "circuit_breaker_open",
                        "circuit_breaker_reset_attempted": True,
                        "reset_result": reset_result
                    },
                    "warning": "Circuit breaker is open due to previous failures. Returning empty result as graceful degradation.",
                    "circuit_breaker_info": reset_result
                }
        
        logger.debug(
            "Getting active alerts with progressive endpoint fallback",
            extra={
                "severity": severity,
                "limit": limit,
                "offset": offset
            }
        )
        
        # Try progressive endpoint fallback
        return await self._get_active_alerts_with_fallback(severity, limit, offset)
    
    async def _get_active_alerts_with_fallback(
        self,
        severity: Optional[str],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Get active alerts using progressive endpoint fallback mechanism.
        
        This method implements intelligent endpoint selection with caching and
        graceful degradation when endpoints fail.
        
        Args:
            severity: Optional severity filter
            limit: Maximum results to return
            offset: Result offset for pagination
            
        Returns:
            Dictionary containing active alerts information
            
        Raises:
            APIError: If all endpoints fail
        """
        # Check for cached successful endpoint first
        cached_config = await self._get_cached_endpoint_config("get_active_alerts")
        
        # Define endpoint configurations in order of preference
        # Based on API discovery service findings and Sumo Logic API patterns
        endpoint_configs = self._get_ordered_endpoint_configs(severity, limit, offset, cached_config)
        
        last_error = None
        attempted_endpoints = []
        fallback_decisions = []
        
        logger.info(
            f"Starting progressive endpoint fallback for active alerts",
            extra={
                "total_endpoints": len(endpoint_configs),
                "has_cached_endpoint": cached_config is not None,
                "cached_endpoint": cached_config.get("name") if cached_config else None
            }
        )
        
        for i, config in enumerate(endpoint_configs):
            is_cached = config.get("is_cached", False)
            
            try:
                logger.debug(
                    f"Attempting endpoint {i+1}/{len(endpoint_configs)}: {config['name']}",
                    extra={
                        "endpoint": config["endpoint"],
                        "params": config["params"],
                        "is_cached": is_cached,
                        "priority": config.get("priority", "normal")
                    }
                )
                
                # Record fallback decision
                fallback_decisions.append({
                    "attempt": i + 1,
                    "endpoint_name": config["name"],
                    "endpoint": config["endpoint"],
                    "reason": "cached_success" if is_cached else "fallback_attempt",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                response = await self._make_request(
                    method="GET",
                    endpoint=config["endpoint"],
                    params=config["params"],
                    operation_type="monitor"
                )
                
                alerts_result = await self._parse_json_response(response)
                
                # Process and filter the response based on the endpoint type
                processed_result = await self._process_alerts_response(
                    alerts_result, config, severity
                )
                
                # Add fallback metadata to response
                processed_result["fallback_info"] = {
                    "endpoint_used": config["name"],
                    "attempt_number": i + 1,
                    "total_attempts": len(endpoint_configs),
                    "was_cached": is_cached,
                    "fallback_decisions": fallback_decisions
                }
                
                logger.info(
                    f"Successfully retrieved active alerts using {config['name']} (attempt {i+1})",
                    extra={
                        "endpoint": config["endpoint"],
                        "alert_count": len(processed_result.get("data", [])),
                        "severity_filter": severity,
                        "was_cached": is_cached,
                        "response_time": processed_result.get("response_time_ms")
                    }
                )
                
                # Cache successful endpoint configuration for future use
                await self._cache_successful_endpoint_config(config)
                
                # Update endpoint success metrics
                await self._update_endpoint_success_metrics(config["name"])
                
                return processed_result
                
            except APIError as e:
                attempted_endpoints.append({
                    "name": config["name"],
                    "endpoint": config["endpoint"],
                    "error": e.message,
                    "status_code": e.status_code,
                    "was_cached": is_cached,
                    "attempt_number": i + 1
                })
                
                logger.warning(
                    f"Endpoint {config['name']} failed (attempt {i+1}): {e.message}",
                    extra={
                        "endpoint": config["endpoint"],
                        "status_code": e.status_code,
                        "error_type": type(e).__name__,
                        "was_cached": is_cached
                    }
                )
                
                # If cached endpoint failed, remove it from cache
                if is_cached:
                    await self._invalidate_cached_endpoint("get_active_alerts")
                    logger.info("Invalidated cached endpoint due to failure")
                
                # Update endpoint failure metrics
                await self._update_endpoint_failure_metrics(config["name"], e.status_code)
                
                last_error = e
                continue
        
        # All endpoints failed - implement graceful degradation
        degraded_response = await self._handle_complete_endpoint_failure(
            attempted_endpoints, fallback_decisions, severity, last_error
        )
        
        if degraded_response:
            return degraded_response
        
        # No graceful degradation possible
        error_summary = {
            "attempted_endpoints": attempted_endpoints,
            "total_attempts": len(endpoint_configs),
            "fallback_decisions": fallback_decisions,
            "last_error": last_error.message if last_error else "Unknown error"
        }
        
        logger.error(
            "All alert endpoint attempts failed - no graceful degradation available",
            extra=error_summary
        )
        
        raise APIError(
            f"Failed to retrieve active alerts after trying {len(endpoint_configs)} endpoints. "
            f"Last error: {last_error.message if last_error else 'Unknown error'}",
            status_code=last_error.status_code if last_error else 500,
            response_body=last_error.response_body if last_error else None,
            request_id=last_error.request_id if last_error else None,
            context={
                "severity": severity,
                "attempted_endpoints": [ep["name"] for ep in attempted_endpoints],
                "endpoint_errors": error_summary,
                "fallback_decisions": fallback_decisions
            }
        )

    async def validate_monitor_query(self, query: str, monitor_type: str = "MonitorsLibraryMonitor") -> Dict[str, Any]:
        """Validate monitor query syntax using dry-run approach.
        
        Args:
            query: Monitor query to validate
            monitor_type: Type of monitor (for context-specific validation)
            
        Returns:
            Dictionary containing validation results
            
        Raises:
            ValidationError: If query is invalid
            APIError: If API request fails
        """
        if not query or not query.strip():
            raise ValidationError(
                "Query cannot be empty",
                field_name="query",
                field_value=query
            )
        
        query = query.strip()
        
        logger.debug(f"Validating monitor query syntax")
        
        try:
            # Use search API with dry-run to validate query syntax
            # This approach validates the query without actually executing it
            validation_payload = {
                "query": query,
                "from": "-1m",  # Minimal time range for validation
                "to": "now",
                "timeZone": "UTC",
                "byReceiptTime": False,
                "validate_only": True  # Custom parameter for validation
            }
            
            # For logs monitors, use search validation
            if monitor_type == "MonitorsLibraryMonitor":
                endpoint = "/api/v1/search/jobs"
                validation_payload["maxCount"] = 1  # Minimal result count
            # For metrics monitors, use metrics validation
            elif monitor_type == "MetricsMonitor":
                endpoint = "/api/v1/metrics/results"
                validation_payload["requestType"] = "MetricsQueryRequest"
            else:
                # For SLI monitors, use basic search validation
                endpoint = "/api/v1/search/jobs"
                validation_payload["maxCount"] = 1
            
            response = await self._make_request(
                method="POST",
                endpoint=endpoint,
                json_data=validation_payload,
                operation_type="search"
            )
            
            result = await self._parse_json_response(response)
            
            logger.info("Query validation completed successfully")
            
            return {
                "valid": True,
                "query": query,
                "monitor_type": monitor_type,
                "validation_method": "dry_run",
                "message": "Query syntax is valid"
            }
            
        except APIError as e:
            # Parse validation errors from API response
            error_message = e.message
            
            # Check if it's a syntax error vs other API error
            if e.status_code == 400 and any(keyword in error_message.lower() for keyword in 
                                          ['syntax', 'parse', 'invalid query', 'malformed']):
                logger.warning(f"Query validation failed: {error_message}")
                return {
                    "valid": False,
                    "query": query,
                    "monitor_type": monitor_type,
                    "validation_method": "dry_run",
                    "error": error_message,
                    "error_type": "syntax_error"
                }
            else:
                # Re-raise non-syntax API errors
                raise APIError(
                    f"Failed to validate query: {e.message}",
                    status_code=e.status_code,
                    response_body=e.response_body,
                    request_id=e.request_id,
                    context={"query": query, "monitor_type": monitor_type}
                ) from e

    async def get_monitor_history(
        self,
        monitor_id: str,
        from_time: str,
        to_time: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get monitor execution history and performance metrics.
        
        Args:
            monitor_id: Unique identifier for the monitor
            from_time: Start time for history range (ISO format or relative like '-1h')
            to_time: End time for history range (ISO format or relative like 'now')
            limit: Maximum number of history entries to return (1-1000)
            
        Returns:
            Dictionary containing monitor execution history and performance metrics
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If API request fails
        """
        if not monitor_id or not isinstance(monitor_id, str):
            raise ValidationError(
                "Monitor ID must be a non-empty string",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        if not from_time or not isinstance(from_time, str):
            raise ValidationError(
                "from_time must be a non-empty string",
                field_name="from_time",
                field_value=from_time
            )
        
        if not to_time or not isinstance(to_time, str):
            raise ValidationError(
                "to_time must be a non-empty string",
                field_name="to_time",
                field_value=to_time
            )
        
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be an integer between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        logger.debug(
            f"Getting monitor history for monitor {monitor_id} from {from_time} to {to_time}"
        )
        
        try:
            # Convert relative time expressions to absolute timestamps if needed
            from_timestamp = self._parse_time_expression(from_time)
            to_timestamp = self._parse_time_expression(to_time)
            
            # Sumo Logic monitor history endpoint
            endpoint = f"/api/v1/monitors/{monitor_id}/history"
            
            params = {
                "from": from_timestamp,
                "to": to_timestamp,
                "limit": limit
            }
            
            response = await self._make_request(
                method="GET",
                endpoint=endpoint,
                params=params,
                operation_type="monitor_management"
            )
            
            result = await self._parse_json_response(response)
            
            logger.info(
                f"Successfully retrieved monitor history for monitor {monitor_id}",
                extra={
                    "monitor_id": monitor_id,
                    "from_time": from_time,
                    "to_time": to_time,
                    "entries_returned": len(result.get("data", []))
                }
            )
            
            return result
            
        except APIError as e:
            if e.status_code == 404:
                raise APIError(
                    f"Monitor not found: {monitor_id}",
                    status_code=404,
                    response_body=e.response_body,
                    request_id=e.request_id,
                    context={"monitor_id": monitor_id}
                ) from e
            elif e.status_code == 403:
                raise APIError(
                    f"Insufficient permissions to access monitor history: {monitor_id}",
                    status_code=403,
                    response_body=e.response_body,
                    request_id=e.request_id,
                    context={"monitor_id": monitor_id}
                ) from e
            else:
                raise APIError(
                    f"Failed to get monitor history: {e.message}",
                    status_code=e.status_code,
                    response_body=e.response_body,
                    request_id=e.request_id,
                    context={"monitor_id": monitor_id, "from_time": from_time, "to_time": to_time}
                ) from e
        
        except Exception as e:
            logger.error(
                f"Unexpected error getting monitor history for monitor {monitor_id}",
                extra={"error": str(e), "error_type": type(e).__name__}
            )
            raise APIError(
                f"Unexpected error getting monitor history: {str(e)}",
                context={"monitor_id": monitor_id, "from_time": from_time, "to_time": to_time}
            ) from e

    def _parse_time_expression(self, time_expr: str) -> str:
        """Parse time expression and convert to appropriate format.
        
        Args:
            time_expr: Time expression (ISO format, 'now', or relative like '-1h')
            
        Returns:
            Formatted time string for API
        """
        import re
        from datetime import datetime, timedelta
        
        time_expr = time_expr.strip()
        
        # Handle 'now' keyword
        if time_expr.lower() == 'now':
            return datetime.utcnow().isoformat() + 'Z'
        
        # Handle relative time expressions like '-1h', '-30m', '-1d'
        relative_pattern = r'^-(\d+)([smhdw])$'
        match = re.match(relative_pattern, time_expr)
        
        if match:
            value, unit = match.groups()
            value = int(value)
            
            # Calculate timedelta based on unit
            if unit == 's':
                delta = timedelta(seconds=value)
            elif unit == 'm':
                delta = timedelta(minutes=value)
            elif unit == 'h':
                delta = timedelta(hours=value)
            elif unit == 'd':
                delta = timedelta(days=value)
            elif unit == 'w':
                delta = timedelta(weeks=value)
            else:
                # Fallback to original expression
                return time_expr
            
            # Calculate absolute time
            absolute_time = datetime.utcnow() - delta
            return absolute_time.isoformat() + 'Z'
        
        # Handle ISO format or other absolute time formats
        # Try to parse as ISO format first
        try:
            # If it's already a valid ISO format, return as-is
            datetime.fromisoformat(time_expr.replace('Z', '+00:00'))
            return time_expr
        except ValueError:
            # If not ISO format, return as-is and let API handle it
            return time_expr

    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def _get_ordered_endpoint_configs(
        self,
        severity: Optional[str],
        limit: int,
        offset: int,
        cached_config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Get endpoint configurations ordered by preference and success history.
        
        Args:
            severity: Optional severity filter
            limit: Maximum results to return
            offset: Result offset for pagination
            cached_config: Previously successful cached configuration
            
        Returns:
            List of endpoint configurations ordered by preference
        """
        # Base endpoint configurations
        base_configs = [
            {
                "name": "monitors_search_critical",
                "endpoint": "/api/v1/monitors/search",
                "params": self._build_search_params("Critical", severity, limit, offset),
                "description": "Monitor search with Critical status",
                "priority": "high"
            },
            {
                "name": "monitors_search_warning",
                "endpoint": "/api/v1/monitors/search", 
                "params": self._build_search_params("Warning", severity, limit, offset),
                "description": "Monitor search with Warning status",
                "priority": "high"
            },
            {
                "name": "monitors_search_all_triggered",
                "endpoint": "/api/v1/monitors/search",
                "params": self._build_search_params("AllTriggered", severity, limit, offset),
                "description": "Monitor search with AllTriggered status",
                "priority": "high"
            },
            {
                "name": "monitors_list_filtered",
                "endpoint": "/api/v1/monitors",
                "params": self._build_monitor_list_params(severity, limit, offset),
                "description": "Monitor list with filtering",
                "priority": "medium"
            },
            {
                "name": "monitors_alerts_no_status",
                "endpoint": "/api/v1/monitors/alerts",
                "params": self._build_alerts_params(None, severity, limit, offset),
                "description": "Alerts endpoint without status parameter",
                "priority": "medium"
            }
        ]
        
        # If we have a cached successful configuration, prioritize it
        if cached_config and self._is_cache_valid(cached_config):
            # Update cached config with current parameters
            cached_config_updated = {
                **cached_config,
                "params": self._update_params_for_request(cached_config, severity, limit, offset),
                "is_cached": True,
                "priority": "cached"
            }
            
            # Remove the cached config from base configs to avoid duplication
            base_configs = [config for config in base_configs 
                          if config["name"] != cached_config["name"]]
            
            # Put cached config first
            return [cached_config_updated] + base_configs
        
        return base_configs
    
    def _build_search_params(
        self,
        monitor_status: str,
        severity: Optional[str],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Build parameters for monitor search endpoint.
        
        Uses the correct Sumo Logic API format where monitorStatus is a filter
        within the query parameter, not a separate parameter.
        
        Args:
            monitor_status: Monitor status filter (Normal, Critical, Warning, MissingData, Disabled, AllTriggered)
            severity: Optional severity filter
            limit: Maximum results
            offset: Result offset
            
        Returns:
            Dictionary of query parameters with proper query string format
            
        Example:
            For Critical status: {"query": "monitorStatus:Critical", "limit": 100, "offset": 0}
            For Warning with severity: {"query": "monitorStatus:Warning AND severity:Critical", "limit": 100, "offset": 0}
        """
        # Build the query string with monitorStatus filter
        # Format: monitorStatus:Critical or monitorStatus:Warning AND severity:Critical
        query_parts = [f"monitorStatus:{monitor_status}"]
        
        # Add severity filter to query if specified
        if severity:
            query_parts.append(f"severity:{severity}")
        
        params = {
            "limit": limit,
            "offset": offset,
            "query": " AND ".join(query_parts)
        }
        
        return params
    
    def _build_monitor_list_params(
        self,
        severity: Optional[str],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Build parameters for monitor list endpoint.
        
        Args:
            severity: Optional severity filter
            limit: Maximum results
            offset: Result offset
            
        Returns:
            Dictionary of query parameters
        """
        params = {
            "limit": limit,
            "offset": offset,
            "isDisabled": False  # Only get enabled monitors
        }
        
        # Note: Monitor list endpoint may not support direct severity filtering
        # We'll filter client-side in _process_alerts_response if needed
        
        return params
    
    def _build_alerts_params(
        self,
        status: Optional[str],
        severity: Optional[str],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Build parameters for alerts endpoint.
        
        Args:
            status: Optional status filter (None to avoid the problematic 'active' parameter)
            severity: Optional severity filter
            limit: Maximum results
            offset: Result offset
            
        Returns:
            Dictionary of query parameters
        """
        params = {
            "limit": limit,
            "offset": offset
        }
        
        # Only add status if explicitly provided and not the problematic 'active'
        if status and status != "active":
            params["status"] = status
        
        # Add severity filter if specified
        if severity:
            params["severity"] = severity
        
        return params
    
    def _update_params_for_request(
        self,
        config: Dict[str, Any],
        severity: Optional[str],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Update cached endpoint parameters for current request.
        
        Args:
            config: Cached endpoint configuration
            severity: Current severity filter
            limit: Current limit
            offset: Current offset
            
        Returns:
            Updated parameters dictionary
        """
        endpoint_name = config.get("name", "")
        
        if "search" in endpoint_name:
            # Determine monitor status based on endpoint name
            if "critical" in endpoint_name:
                monitor_status = "Critical"
            elif "warning" in endpoint_name:
                monitor_status = "Warning"
            elif "all_triggered" in endpoint_name:
                monitor_status = "AllTriggered"
            else:
                monitor_status = "AllTriggered"  # Default fallback
            
            return self._build_search_params(monitor_status, severity, limit, offset)
        elif "monitors" in endpoint_name and "alerts" not in endpoint_name:
            return self._build_monitor_list_params(severity, limit, offset)
        else:
            return self._build_alerts_params(None, severity, limit, offset)
    
    async def _process_alerts_response(
        self,
        response_data: Dict[str, Any],
        endpoint_config: Dict[str, Any],
        severity_filter: Optional[str]
    ) -> Dict[str, Any]:
        """Process and normalize alerts response from different endpoints.
        
        Args:
            response_data: Raw response data from API
            endpoint_config: Configuration of the endpoint used
            severity_filter: Applied severity filter
            
        Returns:
            Normalized alerts response
        """
        endpoint_name = endpoint_config["name"]
        
        # Ensure response_data is a dictionary
        if not isinstance(response_data, dict):
            logger.warning(
                f"Unexpected response format from {endpoint_name}: expected dict, got {type(response_data)}"
            )
            # If response_data is a list, treat it as the data array
            if isinstance(response_data, list):
                response_data = {"data": response_data}
            else:
                # For other types, return empty result
                response_data = {"data": []}
        
        # Handle different response formats based on endpoint type
        if "search" in endpoint_name:
            # Monitor search endpoints typically return monitors, not alerts
            # We need to extract alert information from monitor data
            monitors = response_data.get("data", [])
            if not isinstance(monitors, list):
                logger.warning(f"Expected list for monitors data, got {type(monitors)}")
                monitors = []
            alerts = await self._extract_alerts_from_monitors(monitors, severity_filter)
            
        elif "monitors" in endpoint_name and "alerts" not in endpoint_name:
            # Monitor list endpoint - extract triggered monitors
            monitors = response_data.get("data", [])
            if not isinstance(monitors, list):
                logger.warning(f"Expected list for monitors data, got {type(monitors)}")
                monitors = []
            alerts = await self._extract_alerts_from_monitors(monitors, severity_filter)
            
        else:
            # Direct alerts endpoint
            alerts = response_data.get("data", [])
            if not isinstance(alerts, list):
                logger.warning(f"Expected list for alerts data, got {type(alerts)}")
                alerts = []
            
            # Apply client-side severity filtering if needed
            if severity_filter:
                alerts = [alert for alert in alerts 
                         if isinstance(alert, dict) and alert.get("severity") == severity_filter]
        
        # Normalize response format
        return {
            "data": alerts,
            "total": len(alerts),
            "totalCount": len(alerts),
            "endpoint_used": endpoint_config["endpoint"],
            "endpoint_name": endpoint_name,
            "severity_filter": severity_filter,
            "metadata": {
                "source_endpoint": endpoint_config["endpoint"],
                "processing_method": self._get_processing_method(endpoint_name),
                "filtered_client_side": severity_filter is not None and "search" not in endpoint_name
            }
        }
    
    async def _extract_alerts_from_monitors(
        self,
        monitors: List[Dict[str, Any]],
        severity_filter: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Extract alert information from monitor data.
        
        Args:
            monitors: List of monitor objects
            severity_filter: Optional severity filter to apply
            
        Returns:
            List of alert objects extracted from monitors
        """
        alerts = []
        
        for monitor in monitors:
            # Ensure monitor is a dictionary before processing
            if not isinstance(monitor, dict):
                logger.warning(f"Skipping non-dictionary monitor object: {type(monitor)}")
                continue
                
            # Check if monitor is in a triggered/alert state
            monitor_status = monitor.get("status", "").lower()
            monitor_state = monitor.get("monitorStatus", monitor.get("state", "")).lower()
            is_disabled = monitor.get("isDisabled", False)
            
            # Skip disabled monitors
            if is_disabled:
                continue
            
            # Look for indicators that this monitor has active alerts
            # Based on Sumo Logic monitorStatus values: Normal, Critical, Warning, MissingData, Disabled, AllTriggered
            has_alert = (
                monitor_status in ["critical", "warning", "missingdata", "alltriggered"] or
                monitor_state in ["critical", "warning", "missingdata", "alltriggered"] or
                monitor.get("alertStatus", "").lower() in ["critical", "warning", "missingdata", "alltriggered"]
            )
            
            if has_alert:
                # Extract alert information from monitor
                alert = {
                    "id": monitor.get("id", f"alert_{monitor.get('name', 'unknown')}"),
                    "monitor_id": monitor.get("id"),
                    "monitor_name": monitor.get("name", "Unknown Monitor"),
                    "description": monitor.get("description", ""),
                    "severity": self._extract_severity_from_monitor(monitor),
                    "status": "triggered",
                    "created_at": monitor.get("createdAt"),
                    "modified_at": monitor.get("modifiedAt"),
                    "monitor_type": monitor.get("monitorType", "Unknown"),
                    "is_disabled": is_disabled,
                    "queries": monitor.get("queries", []),
                    "triggers": monitor.get("triggers", []),
                    "notifications": monitor.get("notifications", []),
                    "tags": monitor.get("tags", {}),
                    "metadata": {
                        "extracted_from_monitor": True,
                        "original_status": monitor_status,
                        "monitor_data": monitor
                    }
                }
                
                # Apply severity filter if specified
                if not severity_filter or alert["severity"] == severity_filter:
                    alerts.append(alert)
        
        return alerts
    
    def _extract_severity_from_monitor(self, monitor: Dict[str, Any]) -> str:
        """Extract severity information from monitor data.
        
        Args:
            monitor: Monitor object
            
        Returns:
            Severity string (Critical, Warning, or MissingData)
        """
        # Try various fields that might contain severity information
        # Priority order: monitorStatus, status, severity, state
        severity_fields = [
            monitor.get("monitorStatus"),
            monitor.get("status"),
            monitor.get("severity"),
            monitor.get("alertSeverity"),
            monitor.get("triggerSeverity"),
            monitor.get("state")
        ]
        
        for field_value in severity_fields:
            if field_value:
                field_str = str(field_value).lower()
                if "critical" in field_str:
                    return "Critical"
                elif "warning" in field_str:
                    return "Warning"
                elif "missing" in field_str or "missingdata" in field_str:
                    return "MissingData"
        
        # Default to Warning if no specific severity found
        return "Warning"
    
    def _get_processing_method(self, endpoint_name: str) -> str:
        """Get the processing method description for an endpoint.
        
        Args:
            endpoint_name: Name of the endpoint used
            
        Returns:
            Description of processing method
        """
        if "search" in endpoint_name:
            return "extracted_from_monitor_search"
        elif "monitors" in endpoint_name and "alerts" not in endpoint_name:
            return "extracted_from_monitor_list"
        else:
            return "direct_alerts_endpoint"
    
    async def _get_cached_endpoint_config(self, operation: str) -> Optional[Dict[str, Any]]:
        """Get cached successful endpoint configuration.
        
        Args:
            operation: Operation name (e.g., 'get_active_alerts')
            
        Returns:
            Cached configuration or None if not found/expired
        """
        if not hasattr(self, '_endpoint_cache'):
            return None
        
        cached = self._endpoint_cache.get(operation)
        if not cached:
            return None
        
        # Check if cache is still valid
        if not self._is_cache_valid(cached):
            # Remove expired cache
            del self._endpoint_cache[operation]
            return None
        
        return cached
    
    def _is_cache_valid(self, cached_config: Dict[str, Any]) -> bool:
        """Check if cached endpoint configuration is still valid.
        
        Args:
            cached_config: Cached configuration to validate
            
        Returns:
            True if cache is valid, False otherwise
        """
        if not cached_config.get("cached_at"):
            return False
        
        try:
            cached_time = datetime.fromisoformat(cached_config["cached_at"])
            cache_ttl = cached_config.get("cache_ttl", 3600)  # Default 1 hour
            
            age_seconds = (datetime.utcnow() - cached_time).total_seconds()
            return age_seconds < cache_ttl
            
        except (ValueError, TypeError):
            return False
    
    async def _cache_successful_endpoint_config(self, config: Dict[str, Any]) -> None:
        """Cache successful endpoint configuration for future use.
        
        Args:
            config: Successful endpoint configuration
        """
        if not hasattr(self, '_endpoint_cache'):
            self._endpoint_cache = {}
        
        cache_key = "get_active_alerts"
        current_cache = self._endpoint_cache.get(cache_key, {})
        
        # Enhanced caching with success tracking and TTL
        cached_config = {
            "name": config["name"],
            "endpoint": config["endpoint"],
            "method": config.get("method", "GET"),
            "description": config.get("description", ""),
            "priority": config.get("priority", "normal"),
            "cached_at": datetime.utcnow().isoformat(),
            "success_count": current_cache.get("success_count", 0) + 1,
            "cache_ttl": 3600,  # 1 hour TTL
            "last_used": datetime.utcnow().isoformat(),
            "performance_metrics": {
                "avg_response_time": config.get("response_time_ms", 0),
                "reliability_score": self._calculate_reliability_score(config["name"])
            }
        }
        
        self._endpoint_cache[cache_key] = cached_config
        
        logger.info(
            f"Cached successful endpoint configuration for {cache_key}",
            extra={
                "endpoint": config["endpoint"],
                "endpoint_name": config["name"],
                "success_count": cached_config["success_count"],
                "reliability_score": cached_config["performance_metrics"]["reliability_score"]
            }
        )
    
    async def _invalidate_cached_endpoint(self, operation: str) -> None:
        """Invalidate cached endpoint configuration.
        
        Args:
            operation: Operation name to invalidate
        """
        if hasattr(self, '_endpoint_cache') and operation in self._endpoint_cache:
            del self._endpoint_cache[operation]
            logger.debug(f"Invalidated cached endpoint for {operation}")
    
    async def _update_endpoint_success_metrics(self, endpoint_name: str) -> None:
        """Update success metrics for an endpoint.
        
        Args:
            endpoint_name: Name of successful endpoint
        """
        if not hasattr(self, '_endpoint_metrics'):
            self._endpoint_metrics = {}
        
        if endpoint_name not in self._endpoint_metrics:
            self._endpoint_metrics[endpoint_name] = {
                "success_count": 0,
                "failure_count": 0,
                "last_success": None,
                "last_failure": None
            }
        
        self._endpoint_metrics[endpoint_name]["success_count"] += 1
        self._endpoint_metrics[endpoint_name]["last_success"] = datetime.utcnow().isoformat()
    
    async def _update_endpoint_failure_metrics(self, endpoint_name: str, status_code: Optional[int]) -> None:
        """Update failure metrics for an endpoint.
        
        Args:
            endpoint_name: Name of failed endpoint
            status_code: HTTP status code of failure
        """
        if not hasattr(self, '_endpoint_metrics'):
            self._endpoint_metrics = {}
        
        if endpoint_name not in self._endpoint_metrics:
            self._endpoint_metrics[endpoint_name] = {
                "success_count": 0,
                "failure_count": 0,
                "last_success": None,
                "last_failure": None,
                "failure_codes": {}
            }
        
        metrics = self._endpoint_metrics[endpoint_name]
        metrics["failure_count"] += 1
        metrics["last_failure"] = datetime.utcnow().isoformat()
        
        if status_code:
            if "failure_codes" not in metrics:
                metrics["failure_codes"] = {}
            metrics["failure_codes"][str(status_code)] = metrics["failure_codes"].get(str(status_code), 0) + 1
    
    async def _handle_complete_endpoint_failure(
        self,
        attempted_endpoints: List[Dict[str, Any]],
        fallback_decisions: List[Dict[str, Any]],
        severity_filter: Optional[str],
        last_error: Optional[APIError]
    ) -> Optional[Dict[str, Any]]:
        """Handle complete endpoint failure with graceful degradation.
        
        Args:
            attempted_endpoints: List of attempted endpoints and their errors
            fallback_decisions: List of fallback decisions made
            severity_filter: Applied severity filter
            last_error: Last error encountered
            
        Returns:
            Graceful degradation response or None if not possible
        """
        logger.warning(
            "Implementing graceful degradation for complete endpoint failure",
            extra={
                "attempted_count": len(attempted_endpoints),
                "severity_filter": severity_filter
            }
        )
        
        # Check if we can provide a meaningful empty response
        if self._should_provide_empty_response(attempted_endpoints):
            return {
                "data": [],
                "total": 0,
                "totalCount": 0,
                "endpoint_used": "graceful_degradation",
                "endpoint_name": "empty_response_fallback",
                "severity_filter": severity_filter,
                "metadata": {
                    "source_endpoint": "graceful_degradation",
                    "processing_method": "empty_response_due_to_failures",
                    "degradation_reason": "all_endpoints_failed",
                    "attempted_endpoints": attempted_endpoints,
                    "fallback_decisions": fallback_decisions
                },
                "fallback_info": {
                    "endpoint_used": "graceful_degradation",
                    "attempt_number": len(attempted_endpoints),
                    "total_attempts": len(attempted_endpoints),
                    "was_cached": False,
                    "degradation_applied": True,
                    "fallback_decisions": fallback_decisions
                },
                "warning": "All API endpoints failed. Returning empty result as graceful degradation."
            }
        
        return None
    
    def _should_provide_empty_response(self, attempted_endpoints: List[Dict[str, Any]]) -> bool:
        """Determine if graceful degradation with empty response is appropriate.
        
        Args:
            attempted_endpoints: List of attempted endpoints and their errors
            
        Returns:
            True if empty response degradation is appropriate
        """
        # Provide empty response if all failures are client errors (4xx)
        # This suggests the endpoints exist but parameters are wrong
        client_errors = [ep for ep in attempted_endpoints 
                        if ep.get("status_code") is not None and 
                        ep.get("status_code", 0) >= 400 and ep.get("status_code", 0) < 500]
        
        # If more than half are client errors, it's likely a parameter issue
        # and returning empty is better than failing completely
        return len(client_errors) > len(attempted_endpoints) / 2
    
    def _calculate_reliability_score(self, endpoint_name: str) -> float:
        """Calculate reliability score for an endpoint based on success/failure history.
        
        Args:
            endpoint_name: Name of the endpoint
            
        Returns:
            Reliability score between 0.0 and 1.0
        """
        if not hasattr(self, '_endpoint_metrics') or endpoint_name not in self._endpoint_metrics:
            return 1.0  # New endpoint gets benefit of doubt
        
        metrics = self._endpoint_metrics[endpoint_name]
        success_count = metrics.get("success_count", 0)
        failure_count = metrics.get("failure_count", 0)
        
        total_attempts = success_count + failure_count
        if total_attempts == 0:
            return 1.0
        
        return success_count / total_attempts
    
    def get_endpoint_fallback_status(self) -> Dict[str, Any]:
        """Get status information about endpoint fallback mechanisms.
        
        Returns:
            Dictionary containing fallback status and metrics
        """
        cache_info = {}
        if hasattr(self, '_endpoint_cache'):
            for operation, config in self._endpoint_cache.items():
                cache_info[operation] = {
                    "endpoint_name": config.get("name"),
                    "endpoint": config.get("endpoint"),
                    "cached_at": config.get("cached_at"),
                    "success_count": config.get("success_count", 0),
                    "is_valid": self._is_cache_valid(config),
                    "reliability_score": config.get("performance_metrics", {}).get("reliability_score", 0.0)
                }
        
        metrics_info = {}
        if hasattr(self, '_endpoint_metrics'):
            for endpoint_name, metrics in self._endpoint_metrics.items():
                metrics_info[endpoint_name] = {
                    "success_count": metrics.get("success_count", 0),
                    "failure_count": metrics.get("failure_count", 0),
                    "reliability_score": self._calculate_reliability_score(endpoint_name),
                    "last_success": metrics.get("last_success"),
                    "last_failure": metrics.get("last_failure"),
                    "failure_codes": metrics.get("failure_codes", {})
                }
        
        return {
            "fallback_mechanism": {
                "enabled": True,
                "cache_enabled": True,
                "graceful_degradation": True
            },
            "cached_endpoints": cache_info,
            "endpoint_metrics": metrics_info,
            "summary": {
                "total_cached_operations": len(cache_info),
                "total_tracked_endpoints": len(metrics_info),
                "most_reliable_endpoint": self._get_most_reliable_endpoint()
            }
        }
    
    def _get_most_reliable_endpoint(self) -> Optional[str]:
        """Get the name of the most reliable endpoint based on metrics.
        
        Returns:
            Name of most reliable endpoint or None if no metrics available
        """
        if not hasattr(self, '_endpoint_metrics'):
            return None
        
        best_endpoint = None
        best_score = 0.0
        
        for endpoint_name in self._endpoint_metrics:
            score = self._calculate_reliability_score(endpoint_name)
            if score > best_score:
                best_score = score
                best_endpoint = endpoint_name
        
        return best_endpoint