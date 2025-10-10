"""
Logging and diagnostics utilities for API Discovery Service.

This module provides specialized logging and diagnostic functionality
for API endpoint discovery operations.
"""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DiscoveryLogger:
    """Specialized logger for API discovery operations."""
    
    def __init__(self, log_level: str = "INFO"):
        """Initialize discovery logger.
        
        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = logging.getLogger("sumologic_mcp.discovery")
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Create formatter for structured logging
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Add console handler if not already present
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # Discovery session tracking
        self.session_id = f"discovery_{int(time.time())}"
        self.session_start = datetime.utcnow()
        self.discovery_events: List[Dict[str, Any]] = []
        
        self.logger.info(
            f"Discovery logging session started: {self.session_id}",
            extra={"session_id": self.session_id}
        )
    
    def log_endpoint_test_start(self, endpoint_config: Dict[str, Any]) -> None:
        """Log the start of an endpoint test.
        
        Args:
            endpoint_config: Configuration of endpoint being tested
        """
        event = {
            "event_type": "endpoint_test_start",
            "timestamp": datetime.utcnow().isoformat(),
            "endpoint": endpoint_config.get("endpoint"),
            "method": endpoint_config.get("method"),
            "params": endpoint_config.get("params", {}),
            "name": endpoint_config.get("name")
        }
        
        self.discovery_events.append(event)
        
        self.logger.debug(
            f"Starting endpoint test: {endpoint_config.get('name')}",
            extra={
                "endpoint": endpoint_config.get("endpoint"),
                "method": endpoint_config.get("method"),
                "params": endpoint_config.get("params", {}),
                "session_id": self.session_id
            }
        )
    
    def log_endpoint_test_result(self, result: Dict[str, Any]) -> None:
        """Log the result of an endpoint test.
        
        Args:
            result: Test result dictionary
        """
        event = {
            "event_type": "endpoint_test_result",
            "timestamp": datetime.utcnow().isoformat(),
            "name": result.get("name"),
            "success": result.get("success"),
            "endpoint": result.get("endpoint"),
            "status_code": result.get("status_code"),
            "response_time_ms": result.get("response_time_ms"),
            "error": result.get("error") if not result.get("success") else None
        }
        
        self.discovery_events.append(event)
        
        if result.get("success"):
            self.logger.info(
                f"Endpoint test successful: {result.get('name')}",
                extra={
                    "endpoint": result.get("endpoint"),
                    "status_code": result.get("status_code"),
                    "response_time_ms": result.get("response_time_ms"),
                    "session_id": self.session_id
                }
            )
        else:
            self.logger.warning(
                f"Endpoint test failed: {result.get('name')}",
                extra={
                    "endpoint": result.get("endpoint"),
                    "error": result.get("error"),
                    "status_code": result.get("status_code"),
                    "session_id": self.session_id
                }
            )
    
    def log_discovery_completion(self, discovery_result: Dict[str, Any]) -> None:
        """Log the completion of a discovery operation.
        
        Args:
            discovery_result: Complete discovery result
        """
        event = {
            "event_type": "discovery_completion",
            "timestamp": datetime.utcnow().isoformat(),
            "total_tested": discovery_result.get("summary", {}).get("total_tested", 0),
            "successful_count": discovery_result.get("summary", {}).get("successful_count", 0),
            "failed_count": discovery_result.get("summary", {}).get("failed_count", 0),
            "recommended_endpoint": discovery_result.get("recommendation", {}).get("recommended_endpoint", {}).get("name")
        }
        
        self.discovery_events.append(event)
        
        summary = discovery_result.get("summary", {})
        recommendation = discovery_result.get("recommendation", {})
        
        self.logger.info(
            "API endpoint discovery completed",
            extra={
                "total_tested": summary.get("total_tested", 0),
                "successful_count": summary.get("successful_count", 0),
                "failed_count": summary.get("failed_count", 0),
                "recommended_endpoint": recommendation.get("recommended_endpoint", {}).get("name"),
                "session_id": self.session_id,
                "session_duration_ms": (datetime.utcnow() - self.session_start).total_seconds() * 1000
            }
        )
    
    def log_endpoint_cached(self, operation: str, endpoint_config: Dict[str, Any]) -> None:
        """Log when an endpoint configuration is cached.
        
        Args:
            operation: Operation name
            endpoint_config: Cached endpoint configuration
        """
        event = {
            "event_type": "endpoint_cached",
            "timestamp": datetime.utcnow().isoformat(),
            "operation": operation,
            "endpoint": endpoint_config.get("endpoint"),
            "params": endpoint_config.get("params", {})
        }
        
        self.discovery_events.append(event)
        
        self.logger.info(
            f"Cached successful endpoint for {operation}",
            extra={
                "operation": operation,
                "endpoint": endpoint_config.get("endpoint"),
                "params": endpoint_config.get("params", {}),
                "session_id": self.session_id
            }
        )
    
    def log_diagnostic_info(self, diagnostic_data: Dict[str, Any]) -> None:
        """Log diagnostic information.
        
        Args:
            diagnostic_data: Diagnostic information to log
        """
        self.logger.debug(
            "Discovery service diagnostics",
            extra={
                "diagnostics": diagnostic_data,
                "session_id": self.session_id
            }
        )
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the current discovery session.
        
        Returns:
            Dictionary containing session summary
        """
        session_duration = (datetime.utcnow() - self.session_start).total_seconds()
        
        # Count events by type
        event_counts = {}
        for event in self.discovery_events:
            event_type = event.get("event_type", "unknown")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        # Calculate success/failure rates
        test_results = [e for e in self.discovery_events if e.get("event_type") == "endpoint_test_result"]
        successful_tests = [e for e in test_results if e.get("success")]
        
        return {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat(),
            "session_duration_seconds": round(session_duration, 2),
            "total_events": len(self.discovery_events),
            "event_counts": event_counts,
            "test_statistics": {
                "total_tests": len(test_results),
                "successful_tests": len(successful_tests),
                "failed_tests": len(test_results) - len(successful_tests),
                "success_rate": (len(successful_tests) / len(test_results) * 100) if test_results else 0
            }
        }
    
    def export_session_log(self, file_path: Optional[str] = None) -> str:
        """Export the discovery session log to a file.
        
        Args:
            file_path: Optional file path. If not provided, generates a default name.
            
        Returns:
            Path to the exported log file
        """
        if file_path is None:
            file_path = f"discovery_session_{self.session_id}.json"
        
        session_data = {
            "session_summary": self.get_session_summary(),
            "events": self.discovery_events
        }
        
        try:
            with open(file_path, 'w') as f:
                json.dump(session_data, f, indent=2, default=str)
            
            self.logger.info(f"Discovery session log exported to {file_path}")
            return file_path
            
        except Exception as e:
            self.logger.error(f"Failed to export session log: {e}")
            raise


class DiscoveryDiagnostics:
    """Diagnostic utilities for API discovery operations."""
    
    @staticmethod
    def analyze_endpoint_failures(test_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze endpoint test failures to identify patterns.
        
        Args:
            test_results: List of endpoint test results
            
        Returns:
            Dictionary containing failure analysis
        """
        failed_tests = [r for r in test_results if not r.get("success")]
        
        if not failed_tests:
            return {
                "total_failures": 0,
                "failure_patterns": {},
                "recommendations": ["All endpoints tested successfully"]
            }
        
        # Group failures by status code
        status_code_failures = {}
        error_type_failures = {}
        endpoint_failures = {}
        
        for test in failed_tests:
            status_code = test.get("status_code", "unknown")
            error_type = test.get("error_type", "unknown")
            endpoint = test.get("endpoint", "unknown")
            
            status_code_failures[status_code] = status_code_failures.get(status_code, 0) + 1
            error_type_failures[error_type] = error_type_failures.get(error_type, 0) + 1
            endpoint_failures[endpoint] = endpoint_failures.get(endpoint, 0) + 1
        
        # Generate recommendations based on failure patterns
        recommendations = []
        
        if 400 in status_code_failures:
            recommendations.append("400 errors detected - check parameter formats and API documentation")
        
        if 401 in status_code_failures:
            recommendations.append("401 errors detected - verify API credentials and authentication")
        
        if 404 in status_code_failures:
            recommendations.append("404 errors detected - some endpoints may not exist or be deprecated")
        
        if 429 in status_code_failures:
            recommendations.append("429 errors detected - implement rate limiting or reduce request frequency")
        
        return {
            "total_failures": len(failed_tests),
            "failure_patterns": {
                "by_status_code": status_code_failures,
                "by_error_type": error_type_failures,
                "by_endpoint": endpoint_failures
            },
            "recommendations": recommendations,
            "most_common_failure": max(status_code_failures.items(), key=lambda x: x[1])[0] if status_code_failures else None
        }
    
    @staticmethod
    def generate_endpoint_report(discovery_result: Dict[str, Any]) -> str:
        """Generate a human-readable report of endpoint discovery results.
        
        Args:
            discovery_result: Complete discovery result
            
        Returns:
            Formatted report string
        """
        report_lines = []
        report_lines.append("=== API Endpoint Discovery Report ===")
        report_lines.append(f"Discovery completed at: {discovery_result.get('timestamp', 'unknown')}")
        report_lines.append("")
        
        # Summary section
        summary = discovery_result.get("summary", {})
        report_lines.append("SUMMARY:")
        report_lines.append(f"  Total endpoints tested: {summary.get('total_tested', 0)}")
        report_lines.append(f"  Successful endpoints: {summary.get('successful_count', 0)}")
        report_lines.append(f"  Failed endpoints: {summary.get('failed_count', 0)}")
        
        success_rate = 0
        if summary.get('total_tested', 0) > 0:
            success_rate = (summary.get('successful_count', 0) / summary.get('total_tested', 1)) * 100
        report_lines.append(f"  Success rate: {success_rate:.1f}%")
        report_lines.append("")
        
        # Recommendation section
        recommendation = discovery_result.get("recommendation", {})
        if recommendation.get("status") == "endpoints_found":
            recommended_endpoint = recommendation.get("recommended_endpoint", {})
            report_lines.append("RECOMMENDATION:")
            report_lines.append(f"  Recommended endpoint: {recommended_endpoint.get('name', 'unknown')}")
            report_lines.append(f"  URL: {recommended_endpoint.get('endpoint', 'unknown')}")
            report_lines.append(f"  Method: {recommended_endpoint.get('method', 'unknown')}")
            report_lines.append(f"  Parameters: {recommended_endpoint.get('params', {})}")
            report_lines.append(f"  Reason: {recommended_endpoint.get('reason', 'No reason provided')}")
        else:
            report_lines.append("RECOMMENDATION:")
            report_lines.append("  No working endpoints found")
            suggested_actions = recommendation.get("suggested_actions", [])
            if suggested_actions:
                report_lines.append("  Suggested actions:")
                for action in suggested_actions:
                    report_lines.append(f"    - {action}")
        
        report_lines.append("")
        
        # Detailed results section
        report_lines.append("DETAILED RESULTS:")
        tested_endpoints = discovery_result.get("tested_endpoints", [])
        
        successful_endpoints = [e for e in tested_endpoints if e.get("success")]
        failed_endpoints = [e for e in tested_endpoints if not e.get("success")]
        
        if successful_endpoints:
            report_lines.append("  Successful endpoints:")
            for endpoint in successful_endpoints:
                report_lines.append(f"    ✓ {endpoint.get('name', 'unknown')}")
                report_lines.append(f"      URL: {endpoint.get('endpoint', 'unknown')}")
                report_lines.append(f"      Response time: {endpoint.get('response_time_ms', 0):.1f}ms")
                report_lines.append(f"      Status code: {endpoint.get('status_code', 'unknown')}")
        
        if failed_endpoints:
            report_lines.append("  Failed endpoints:")
            for endpoint in failed_endpoints:
                report_lines.append(f"    ✗ {endpoint.get('name', 'unknown')}")
                report_lines.append(f"      URL: {endpoint.get('endpoint', 'unknown')}")
                report_lines.append(f"      Error: {endpoint.get('error', 'Unknown error')}")
                report_lines.append(f"      Status code: {endpoint.get('status_code', 'unknown')}")
        
        report_lines.append("")
        report_lines.append("=== End of Report ===")
        
        return "\n".join(report_lines)
    
    @staticmethod
    def validate_discovery_configuration(config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate discovery service configuration.
        
        Args:
            config: Discovery configuration to validate
            
        Returns:
            Dictionary containing validation results
        """
        validation_results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
        # Check required configuration fields
        required_fields = ["endpoint", "timeout", "max_retries"]
        for field in required_fields:
            if not hasattr(config, field) or getattr(config, field) is None:
                validation_results["errors"].append(f"Missing required configuration field: {field}")
                validation_results["valid"] = False
        
        # Check timeout values
        if hasattr(config, "timeout") and config.timeout:
            if config.timeout < 5:
                validation_results["warnings"].append("Timeout is very low (< 5s), may cause premature failures")
            elif config.timeout > 60:
                validation_results["warnings"].append("Timeout is very high (> 60s), may slow down discovery")
        
        # Check retry configuration
        if hasattr(config, "max_retries") and config.max_retries:
            if config.max_retries < 1:
                validation_results["warnings"].append("Max retries is 0, no retry attempts will be made")
            elif config.max_retries > 5:
                validation_results["warnings"].append("Max retries is high (> 5), may slow down discovery")
        
        # Check endpoint URL format
        if hasattr(config, "endpoint") and config.endpoint:
            if not config.endpoint.startswith(("http://", "https://")):
                validation_results["errors"].append("Endpoint URL must start with http:// or https://")
                validation_results["valid"] = False
            
            if "sumologic" not in config.endpoint.lower():
                validation_results["warnings"].append("Endpoint URL doesn't contain 'sumologic', verify it's correct")
        
        # Generate recommendations
        if validation_results["valid"]:
            validation_results["recommendations"].append("Configuration appears valid for discovery operations")
        
        if validation_results["warnings"]:
            validation_results["recommendations"].append("Review warnings to optimize discovery performance")
        
        return validation_results