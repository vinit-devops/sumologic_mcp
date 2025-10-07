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
    SumoLogicError
)
from .resilience import (
    ResilientAPIClient,
    RetryConfig,
    CircuitBreakerConfig,
    TimeoutManager
)
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
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for API requests.
        
        Returns:
            Configured HTTP client instance
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
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
            from_time: Start time (ISO format or relative like '-1h')
            to_time: End time (ISO format or relative like 'now')
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
        # Validate search request
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
                f"Invalid search parameters: {e}",
                validation_errors={err['loc'][0]: err['msg'] for err in e.errors()},
                context={"query": query, "from_time": from_time, "to_time": to_time}
            ) from e
        
        # Parse and validate time range
        try:
            start_dt, end_dt = TimeParser.validate_time_range(
                search_request.from_time, 
                search_request.to_time
            )
            
            # Convert to Sumo Logic API format
            from_time_formatted = TimeParser.to_sumo_time_format(start_dt)
            to_time_formatted = TimeParser.to_sumo_time_format(end_dt)
            
        except ValueError as e:
            raise ValidationError(
                f"Invalid time range: {e}",
                field_name="time_range",
                context={"from_time": search_request.from_time, "to_time": search_request.to_time}
            ) from e
        
        # Build search request payload
        search_payload = {
            "query": search_request.query,
            "from": from_time_formatted,
            "to": to_time_formatted,
            "timeZone": search_request.time_zone or "UTC",
            "byReceiptTime": search_request.by_receipt_time
        }
        
        if search_request.auto_parsing_mode:
            search_payload["autoParsingMode"] = search_request.auto_parsing_mode
        
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
            ValidationError: If job_id is invalid
            SearchError: If status check fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise ValidationError(
                "Job ID cannot be empty",
                field_name="job_id",
                field_value=job_id
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
            ValidationError: If parameters are invalid
            SearchError: If results retrieval fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise ValidationError(
                "Job ID cannot be empty",
                field_name="job_id",
                field_value=job_id
            )
        
        if offset < 0:
            raise ValidationError(
                "Offset must be non-negative",
                field_name="offset",
                field_value=offset
            )
        
        if limit < 1 or limit > 10000:
            raise ValidationError(
                "Limit must be between 1 and 10000",
                field_name="limit",
                field_value=limit
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
            ValidationError: If job_id is invalid
            SearchError: If cancellation fails
            APIError: If API request fails
        """
        if not job_id or not job_id.strip():
            raise ValidationError(
                "Job ID cannot be empty",
                field_name="job_id",
                field_value=job_id
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
        
        # Parse and validate time range
        try:
            start_dt, end_dt = TimeParser.validate_time_range(from_time, to_time)
            
            # For metrics API, we can use relative time if it's in the original format
            # or convert to epoch milliseconds
            if TimeParser._is_relative_time(from_time) or from_time.lower() == 'now':
                from_time_value = from_time
                from_time_type = "RelativeTimeRangeBoundary"
                from_time_key = "relativeTime"
            else:
                from_time_value = str(int(start_dt.timestamp() * 1000))
                from_time_type = "EpochTimeRangeBoundary"
                from_time_key = "epochMillis"
            
            if TimeParser._is_relative_time(to_time) or to_time.lower() == 'now':
                to_time_value = to_time
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
                context={"from_time": from_time, "to_time": to_time}
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
            extra={"name": config.name}
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

    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()