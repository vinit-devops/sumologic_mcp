"""
API Discovery Service for Sumo Logic MCP server.

This module implements endpoint discovery functionality to test and validate
different Sumo Logic API endpoints for alert monitoring operations.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from .api_client import SumoLogicAPIClient
from .exceptions import APIError, ValidationError, TimeoutError
from .auth import SumoLogicAuth
from .discovery_logging import DiscoveryLogger, DiscoveryDiagnostics

logger = logging.getLogger(__name__)


class APIDiscoveryService:
    """Service to discover and test correct API endpoints for alert operations."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize API discovery service.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
        self.config = api_client.config
        self.auth = api_client.auth
        
        # Initialize discovery logger
        self.discovery_logger = DiscoveryLogger()
        
        # Cache for successful endpoint configurations
        self._endpoint_cache: Dict[str, Dict[str, Any]] = {}
        
        # Discovery results storage
        self._discovery_results: Dict[str, List[Dict[str, Any]]] = {}
        
        # Store initialization time for diagnostics
        self._initialized_at = datetime.utcnow().isoformat()
        
        logger.info(
            "Initialized API Discovery Service",
            extra={
                "endpoint": self.config.endpoint,
                "cache_enabled": True
            }
        )
    
    async def discover_alerts_endpoint(self) -> Dict[str, Any]:
        """Discover the correct endpoint for active alerts retrieval.
        
        Returns:
            Dictionary containing discovery results and recommendations
        """
        logger.info("Starting API endpoint discovery for active alerts")
        
        # Define candidate endpoints to test
        candidate_endpoints = [
            {
                "name": "monitors_search_critical",
                "endpoint": "/api/v1/monitors/search",
                "method": "GET",
                "params": {"query": "monitorStatus:Critical", "limit": 1},
                "description": "Search monitors with Critical status"
            },
            {
                "name": "monitors_search_warning",
                "endpoint": "/api/v1/monitors/search",
                "method": "GET", 
                "params": {"query": "monitorStatus:Warning", "limit": 1},
                "description": "Search monitors with Warning status"
            },
            {
                "name": "monitors_search_all_triggered",
                "endpoint": "/api/v1/monitors/search",
                "method": "GET",
                "params": {"query": "monitorStatus:AllTriggered", "limit": 1},
                "description": "Search monitors with AllTriggered status"
            },
            {
                "name": "monitors_list_basic",
                "endpoint": "/api/v1/monitors",
                "method": "GET",
                "params": {"limit": 1},
                "description": "Basic monitors list endpoint"
            },
            {
                "name": "monitors_alerts_original",
                "endpoint": "/api/v1/monitors/alerts",
                "method": "GET",
                "params": {"limit": 1},
                "description": "Original alerts endpoint without status parameter"
            },
            {
                "name": "monitors_alerts_active",
                "endpoint": "/api/v1/monitors/alerts",
                "method": "GET",
                "params": {"status": "active", "limit": 1},
                "description": "Original alerts endpoint with active status (current failing implementation)"
            },
            {
                "name": "alerts_direct",
                "endpoint": "/api/v1/alerts",
                "method": "GET",
                "params": {"limit": 1},
                "description": "Direct alerts endpoint"
            },
            {
                "name": "alerts_active",
                "endpoint": "/api/v1/alerts",
                "method": "GET",
                "params": {"status": "active", "limit": 1},
                "description": "Direct alerts endpoint with active status"
            }
        ]
        
        discovery_results = []
        successful_endpoints = []
        
        # Test each candidate endpoint
        for candidate in candidate_endpoints:
            logger.debug(f"Testing endpoint: {candidate['name']}")
            
            try:
                result = await self._test_endpoint_configuration(candidate)
                discovery_results.append(result)
                
                if result["success"]:
                    successful_endpoints.append(result)
                    logger.info(
                        f"Endpoint test successful: {candidate['name']}",
                        extra={
                            "endpoint": candidate["endpoint"],
                            "response_time": result.get("response_time_ms"),
                            "status_code": result.get("status_code")
                        }
                    )
                else:
                    logger.warning(
                        f"Endpoint test failed: {candidate['name']}",
                        extra={
                            "endpoint": candidate["endpoint"],
                            "error": result.get("error"),
                            "status_code": result.get("status_code")
                        }
                    )
                    
            except Exception as e:
                logger.error(
                    f"Unexpected error testing endpoint {candidate['name']}: {e}",
                    extra={"endpoint": candidate["endpoint"]}
                )
                discovery_results.append({
                    "name": candidate["name"],
                    "success": False,
                    "error": f"Unexpected error: {str(e)}",
                    "error_type": "discovery_error"
                })
        
        # Store results for future reference
        self._discovery_results["alerts_endpoints"] = discovery_results
        
        # Analyze results and provide recommendations
        recommendation = self._analyze_discovery_results(successful_endpoints, discovery_results)
        
        # Create final discovery result
        discovery_result = {
            "discovery_completed": True,
            "timestamp": datetime.utcnow().isoformat(),
            "tested_endpoints": discovery_results,
            "successful_endpoints": successful_endpoints,
            "recommendation": recommendation,
            "summary": {
                "total_tested": len(candidate_endpoints),
                "successful_count": len(successful_endpoints),
                "failed_count": len(discovery_results) - len(successful_endpoints)
            },
            "diagnostics": DiscoveryDiagnostics.analyze_endpoint_failures(discovery_results)
        }
        
        # Log discovery completion
        self.discovery_logger.log_discovery_completion(discovery_result)
        
        logger.info(
            "API endpoint discovery completed",
            extra={
                "total_tested": len(candidate_endpoints),
                "successful": len(successful_endpoints),
                "recommended_endpoint": recommendation.get("recommended_endpoint", {}).get("name")
            }
        )
        
        return discovery_result
    
    async def _test_endpoint_configuration(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test a specific endpoint configuration.
        
        Args:
            config: Endpoint configuration to test
            
        Returns:
            Dictionary containing test results
        """
        # Log test start
        self.discovery_logger.log_endpoint_test_start(config)
        
        start_time = time.time()
        
        try:
            # Make the API request using the configured client
            response = await self.api_client._make_request(
                method=config["method"],
                endpoint=config["endpoint"],
                params=config.get("params"),
                operation_type="discovery"
            )
            
            response_time = (time.time() - start_time) * 1000
            
            # Parse response to check structure
            try:
                response_data = await self.api_client._parse_json_response(response)
                data_structure = self._analyze_response_structure(response_data)
            except Exception as parse_error:
                logger.warning(f"Failed to parse response for {config['name']}: {parse_error}")
                data_structure = {"parse_error": str(parse_error)}
            
            result = {
                "name": config["name"],
                "success": True,
                "endpoint": config["endpoint"],
                "method": config["method"],
                "params": config.get("params", {}),
                "status_code": response.status_code,
                "response_time_ms": round(response_time, 2),
                "response_size": len(response.content) if response.content else 0,
                "data_structure": data_structure,
                "headers": dict(response.headers),
                "description": config.get("description", "")
            }
            
            # Log successful test result
            self.discovery_logger.log_endpoint_test_result(result)
            return result
            
        except APIError as e:
            response_time = (time.time() - start_time) * 1000
            
            result = {
                "name": config["name"],
                "success": False,
                "endpoint": config["endpoint"],
                "method": config["method"],
                "params": config.get("params", {}),
                "status_code": e.status_code,
                "response_time_ms": round(response_time, 2),
                "error": e.message,
                "error_type": "api_error",
                "response_body": e.response_body[:500] if e.response_body else None,
                "description": config.get("description", "")
            }
            
            # Log failed test result
            self.discovery_logger.log_endpoint_test_result(result)
            return result
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            
            result = {
                "name": config["name"],
                "success": False,
                "endpoint": config["endpoint"],
                "method": config["method"],
                "params": config.get("params", {}),
                "response_time_ms": round(response_time, 2),
                "error": str(e),
                "error_type": "unexpected_error",
                "description": config.get("description", "")
            }
            
            # Log failed test result
            self.discovery_logger.log_endpoint_test_result(result)
            return result
    
    def _analyze_response_structure(self, response_data: Any) -> Dict[str, Any]:
        """Analyze the structure of API response data.
        
        Args:
            response_data: Parsed response data
            
        Returns:
            Dictionary describing the response structure
        """
        if isinstance(response_data, dict):
            structure = {
                "type": "object",
                "keys": list(response_data.keys()),
                "has_data_key": "data" in response_data,
                "has_alerts": any(key in response_data for key in ["alerts", "data"]),
                "total_keys": len(response_data.keys())
            }
            
            # Analyze data array if present
            if "data" in response_data and isinstance(response_data["data"], list):
                data_array = response_data["data"]
                structure["data_array"] = {
                    "length": len(data_array),
                    "sample_item_keys": list(data_array[0].keys()) if data_array else []
                }
            
            return structure
            
        elif isinstance(response_data, list):
            return {
                "type": "array",
                "length": len(response_data),
                "sample_item_keys": list(response_data[0].keys()) if response_data and isinstance(response_data[0], dict) else []
            }
        else:
            return {
                "type": type(response_data).__name__,
                "value": str(response_data)[:100]
            }
    
    def _analyze_discovery_results(
        self,
        successful_endpoints: List[Dict[str, Any]],
        all_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze discovery results and provide recommendations.
        
        Args:
            successful_endpoints: List of successful endpoint tests
            all_results: List of all endpoint test results
            
        Returns:
            Dictionary containing analysis and recommendations
        """
        if not successful_endpoints:
            return {
                "status": "no_working_endpoints",
                "message": "No working endpoints found for alert retrieval",
                "suggested_actions": [
                    "Check API credentials and permissions",
                    "Verify Sumo Logic API endpoint URL",
                    "Review API documentation for correct endpoints",
                    "Check network connectivity to Sumo Logic"
                ],
                "failed_endpoints": [result["name"] for result in all_results if not result["success"]]
            }
        
        # Score endpoints based on various criteria
        scored_endpoints = []
        for endpoint in successful_endpoints:
            score = self._calculate_endpoint_score(endpoint)
            scored_endpoints.append({
                **endpoint,
                "score": score
            })
        
        # Sort by score (highest first)
        scored_endpoints.sort(key=lambda x: x["score"], reverse=True)
        best_endpoint = scored_endpoints[0]
        
        # Generate recommendation
        recommendation = {
            "status": "endpoints_found",
            "recommended_endpoint": {
                "name": best_endpoint["name"],
                "endpoint": best_endpoint["endpoint"],
                "method": best_endpoint["method"],
                "params": best_endpoint["params"],
                "score": best_endpoint["score"],
                "reason": self._get_recommendation_reason(best_endpoint)
            },
            "alternative_endpoints": [
                {
                    "name": ep["name"],
                    "endpoint": ep["endpoint"],
                    "params": ep["params"],
                    "score": ep["score"]
                }
                for ep in scored_endpoints[1:3]  # Top 2 alternatives
            ],
            "implementation_guidance": self._generate_implementation_guidance(best_endpoint)
        }
        
        return recommendation
    
    def _calculate_endpoint_score(self, endpoint: Dict[str, Any]) -> float:
        """Calculate a score for an endpoint based on various criteria.
        
        Args:
            endpoint: Endpoint test result
            
        Returns:
            Score value (higher is better)
        """
        score = 0.0
        
        # Base score for working endpoint
        score += 10.0
        
        # Response time bonus (faster is better)
        response_time = endpoint.get("response_time_ms", 1000)
        if response_time < 500:
            score += 5.0
        elif response_time < 1000:
            score += 3.0
        elif response_time < 2000:
            score += 1.0
        
        # Data structure bonus
        data_structure = endpoint.get("data_structure", {})
        if data_structure.get("has_data_key"):
            score += 3.0
        if data_structure.get("has_alerts"):
            score += 5.0
        
        # Endpoint name preferences (based on likely correctness)
        name = endpoint.get("name", "")
        if "search" in name and ("critical" in name or "warning" in name or "all_triggered" in name):
            score += 8.0  # Likely the most correct approach using proper monitorStatus
        elif "alerts" in name and "active" not in name:
            score += 6.0  # Alerts endpoint without problematic parameter
        elif "monitors" in name and "basic" in name:
            score += 4.0  # Basic monitors endpoint
        elif "active" in name:
            score -= 5.0  # Penalize endpoints with "active" parameter (known issue)
        
        # Status code bonus
        status_code = endpoint.get("status_code", 500)
        if status_code == 200:
            score += 2.0
        
        return score
    
    def _get_recommendation_reason(self, endpoint: Dict[str, Any]) -> str:
        """Generate a human-readable reason for the recommendation.
        
        Args:
            endpoint: Recommended endpoint
            
        Returns:
            Explanation string
        """
        reasons = []
        
        name = endpoint.get("name", "")
        response_time = endpoint.get("response_time_ms", 0)
        data_structure = endpoint.get("data_structure", {})
        
        if "search" in name and ("critical" in name or "warning" in name or "all_triggered" in name):
            reasons.append("uses monitor search with proper monitorStatus filter")
        elif "alerts" in name:
            reasons.append("directly accesses alerts endpoint")
        
        if response_time < 500:
            reasons.append("fast response time")
        
        if data_structure.get("has_data_key"):
            reasons.append("returns structured data format")
        
        if data_structure.get("has_alerts"):
            reasons.append("contains alert information")
        
        return f"Recommended because it {', '.join(reasons)}"
    
    def _generate_implementation_guidance(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """Generate implementation guidance for the recommended endpoint.
        
        Args:
            endpoint: Recommended endpoint
            
        Returns:
            Implementation guidance dictionary
        """
        guidance = {
            "endpoint_url": endpoint["endpoint"],
            "http_method": endpoint["method"],
            "required_parameters": endpoint.get("params", {}),
            "expected_response_format": endpoint.get("data_structure", {}),
            "implementation_notes": []
        }
        
        name = endpoint.get("name", "")
        
        if "search" in name:
            guidance["implementation_notes"].extend([
                "Use monitor search endpoint with appropriate state/status filters",
                "Consider pagination for large result sets",
                "Filter results client-side if needed for specific alert criteria"
            ])
        elif "alerts" in name:
            guidance["implementation_notes"].extend([
                "Direct alerts endpoint access",
                "May require different parameter format than monitors",
                "Check response structure for alert-specific fields"
            ])
        
        # Add parameter guidance
        params = endpoint.get("params", {})
        if "query" in params and "monitorStatus:" in params["query"]:
            guidance["implementation_notes"].append(
                f"Use 'query' parameter with monitorStatus filter: '{params['query']}'"
            )
        elif "status" in params and params["status"] != "active":
            guidance["implementation_notes"].append(
                f"Use 'status' parameter with value '{params['status']}' for filtering"
            )
        
        return guidance
    
    async def test_endpoint_with_parameters(
        self,
        endpoint: str,
        method: str = "GET",
        parameter_combinations: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Test an endpoint with multiple parameter combinations.
        
        Args:
            endpoint: API endpoint to test
            method: HTTP method to use
            parameter_combinations: List of parameter dictionaries to test
            
        Returns:
            Dictionary containing test results for all parameter combinations
        """
        if parameter_combinations is None:
            parameter_combinations = [
                {},  # No parameters
                {"limit": 10},  # Basic limit
                {"limit": 10, "offset": 0},  # Pagination
            ]
        
        logger.info(
            f"Testing endpoint {endpoint} with {len(parameter_combinations)} parameter combinations"
        )
        
        test_results = []
        
        for i, params in enumerate(parameter_combinations):
            logger.debug(f"Testing parameter combination {i + 1}: {params}")
            
            config = {
                "name": f"test_{i + 1}",
                "endpoint": endpoint,
                "method": method,
                "params": params,
                "description": f"Parameter test {i + 1}"
            }
            
            result = await self._test_endpoint_configuration(config)
            test_results.append(result)
        
        # Analyze results
        successful_tests = [r for r in test_results if r["success"]]
        failed_tests = [r for r in test_results if not r["success"]]
        
        return {
            "endpoint": endpoint,
            "method": method,
            "total_tests": len(parameter_combinations),
            "successful_tests": len(successful_tests),
            "failed_tests": len(failed_tests),
            "test_results": test_results,
            "best_parameters": successful_tests[0]["params"] if successful_tests else None,
            "summary": {
                "success_rate": len(successful_tests) / len(parameter_combinations) * 100,
                "fastest_response": min((r.get("response_time_ms", float('inf')) for r in successful_tests), default=None),
                "common_errors": self._analyze_common_errors(failed_tests)
            }
        }
    
    def _analyze_common_errors(self, failed_tests: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze common error patterns in failed tests.
        
        Args:
            failed_tests: List of failed test results
            
        Returns:
            Dictionary mapping error types to occurrence counts
        """
        error_counts = {}
        
        for test in failed_tests:
            error_type = test.get("error_type", "unknown")
            status_code = test.get("status_code")
            
            if status_code:
                key = f"{error_type}_{status_code}"
            else:
                key = error_type
            
            error_counts[key] = error_counts.get(key, 0) + 1
        
        return error_counts
    
    def get_cached_endpoint(self, operation: str) -> Optional[Dict[str, Any]]:
        """Get cached successful endpoint configuration for an operation.
        
        Args:
            operation: Operation name (e.g., 'get_active_alerts')
            
        Returns:
            Cached endpoint configuration or None if not found
        """
        return self._endpoint_cache.get(operation)
    
    def cache_successful_endpoint(
        self,
        operation: str,
        endpoint_config: Dict[str, Any]
    ) -> None:
        """Cache a successful endpoint configuration for future use.
        
        Args:
            operation: Operation name
            endpoint_config: Successful endpoint configuration
        """
        cached_config = {
            **endpoint_config,
            "cached_at": datetime.utcnow().isoformat(),
            "cache_ttl": 3600  # 1 hour TTL
        }
        
        self._endpoint_cache[operation] = cached_config
        
        # Log caching operation
        self.discovery_logger.log_endpoint_cached(operation, endpoint_config)
        
        logger.info(
            f"Cached successful endpoint for {operation}",
            extra={
                "endpoint": endpoint_config.get("endpoint"),
                "params": endpoint_config.get("params")
            }
        )
    
    def get_discovery_diagnostics(self) -> Dict[str, Any]:
        """Get diagnostic information about discovery operations.
        
        Returns:
            Dictionary containing diagnostic information
        """
        diagnostics = {
            "cache_status": {
                "cached_operations": list(self._endpoint_cache.keys()),
                "cache_size": len(self._endpoint_cache)
            },
            "discovery_history": {
                "operations": list(self._discovery_results.keys()),
                "total_discoveries": len(self._discovery_results)
            },
            "service_info": {
                "api_endpoint": self.config.endpoint,
                "initialized_at": getattr(self, '_initialized_at', 'unknown')
            },
            "session_summary": self.discovery_logger.get_session_summary(),
            "configuration_validation": DiscoveryDiagnostics.validate_discovery_configuration(self.config)
        }
        
        # Log diagnostic information
        self.discovery_logger.log_diagnostic_info(diagnostics)
        
        return diagnostics
    
    def generate_discovery_report(self, discovery_result: Dict[str, Any]) -> str:
        """Generate a human-readable discovery report.
        
        Args:
            discovery_result: Discovery result to generate report for
            
        Returns:
            Formatted report string
        """
        return DiscoveryDiagnostics.generate_endpoint_report(discovery_result)
    
    def export_discovery_session(self, file_path: Optional[str] = None) -> str:
        """Export the current discovery session to a file.
        
        Args:
            file_path: Optional file path for export
            
        Returns:
            Path to exported file
        """
        return self.discovery_logger.export_session_log(file_path)