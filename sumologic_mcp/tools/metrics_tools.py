"""
Metrics tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic metrics operations including
time-series data querying, metric source discovery, and query validation.
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timedelta
import re

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError

logger = logging.getLogger(__name__)


class MetricsTools:
    """MCP tools for Sumo Logic metrics operations."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize MetricsTools with API client.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
    
    async def query_metrics(
        self,
        query: str,
        from_time: str,
        to_time: str,
        quantization: Optional[int] = None,
        rollup: Optional[str] = None,
        max_data_points: int = 1000
    ) -> Dict[str, Any]:
        """Execute metrics query and return time-series data.
        
        This tool executes a metrics query against Sumo Logic's Metrics API
        and returns formatted time-series data with proper aggregation.
        
        Args:
            query: Metrics query using Sumo Logic metrics query language
            from_time: Start time (ISO format, relative time, or epoch)
            to_time: End time (ISO format, relative time, or epoch)
            quantization: Time bucket size in seconds for data aggregation
            rollup: Rollup type for aggregation (Avg, Sum, Min, Max, Count)
            max_data_points: Maximum number of data points to return (1-10000)
            
        Returns:
            Dict containing time-series metrics data:
            {
                "query": str,
                "from_time": str,
                "to_time": str,
                "time_series": List[Dict],
                "metadata": Dict,
                "data_points_count": int,
                "quantization_seconds": int
            }
            
        Raises:
            ValidationError: If query parameters are invalid
            APIError: If metrics query execution fails
        """
        try:
            # Validate query parameters
            if not query or not isinstance(query, str):
                raise ValidationError("Query must be a non-empty string")
            
            if not from_time or not to_time:
                raise ValidationError("Both from_time and to_time are required")
            
            if max_data_points < 1 or max_data_points > 10000:
                raise ValidationError("max_data_points must be between 1 and 10000")
            
            # Validate rollup type if provided
            valid_rollups = ["Avg", "Sum", "Min", "Max", "Count", "None"]
            if rollup and rollup not in valid_rollups:
                raise ValidationError(f"rollup must be one of: {', '.join(valid_rollups)}")
            
            # Validate metrics query syntax
            self._validate_metrics_query(query)
            
            logger.info(f"Executing metrics query: {query[:100]}...")
            
            # Execute metrics query via API
            metrics_response = await self.api_client.query_metrics(
                query=query,
                from_time=from_time,
                to_time=to_time,
                quantization=quantization,
                rollup=rollup,
                max_data_points=max_data_points
            )
            
            # Extract and format time-series data
            time_series = metrics_response.get("response", [])
            
            # Format time-series data
            formatted_series = []
            total_data_points = 0
            
            for series in time_series:
                series_data = {
                    "metric": series.get("metric", {}),
                    "values": series.get("values", []),
                    "timestamps": series.get("timestamps", []),
                    "labels": series.get("labels", {}),
                    "data_points": len(series.get("values", []))
                }
                
                # Convert timestamps to ISO format if they're in epoch
                formatted_timestamps = []
                for ts in series_data["timestamps"]:
                    if isinstance(ts, (int, float)):
                        # Convert epoch milliseconds to ISO format
                        dt = datetime.fromtimestamp(ts / 1000)
                        formatted_timestamps.append(dt.isoformat())
                    else:
                        formatted_timestamps.append(ts)
                
                series_data["timestamps"] = formatted_timestamps
                formatted_series.append(series_data)
                total_data_points += series_data["data_points"]
            
            # Extract metadata
            metadata = {
                "query_type": "metrics",
                "execution_time_ms": metrics_response.get("executionTimeMs", 0),
                "series_count": len(formatted_series),
                "quantization_used": metrics_response.get("quantization", quantization),
                "rollup_used": metrics_response.get("rollup", rollup),
                "time_range_ms": self._calculate_time_range_ms(from_time, to_time)
            }
            
            formatted_response = {
                "query": query,
                "from_time": from_time,
                "to_time": to_time,
                "time_series": formatted_series,
                "metadata": metadata,
                "data_points_count": total_data_points,
                "quantization_seconds": metadata["quantization_used"],
                "success": True
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Metrics query validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Metrics query API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error executing metrics query: {e}")
            raise APIError(f"Failed to execute metrics query: {str(e)}")
    
    async def list_metric_sources(
        self,
        filter_pattern: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """List available metric sources for discovery.
        
        This tool discovers available metric sources in Sumo Logic,
        helping users understand what metrics are available for querying.
        
        Args:
            filter_pattern: Optional regex pattern to filter metric names
            limit: Maximum number of metric sources to return (1-1000)
            
        Returns:
            Dict containing metric sources information:
            {
                "metric_sources": List[Dict],
                "total_count": int,
                "filter_applied": bool,
                "categories": Dict[str, int]
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If metric source listing fails
        """
        try:
            # Validate parameters
            if limit < 1 or limit > 1000:
                raise ValidationError("Limit must be between 1 and 1000")
            
            if filter_pattern:
                try:
                    re.compile(filter_pattern)
                except re.error as e:
                    raise ValidationError(f"Invalid regex pattern: {e}")
            
            logger.info(f"Listing metric sources with filter='{filter_pattern}', limit={limit}")
            
            # Get metric sources from API
            sources_response = await self.api_client.list_metric_sources(
                filter_pattern=filter_pattern,
                limit=limit
            )
            
            # Extract and format metric sources
            sources = sources_response.get("sources", [])
            
            formatted_sources = []
            categories = {}
            
            for source in sources:
                # Extract metric information
                metric_info = {
                    "name": source.get("name", ""),
                    "description": source.get("description", ""),
                    "category": source.get("category", "uncategorized"),
                    "dimensions": source.get("dimensions", []),
                    "unit": source.get("unit", ""),
                    "type": source.get("type", "gauge"),
                    "last_updated": source.get("lastUpdated"),
                    "sample_rate": source.get("sampleRate"),
                    "retention_period": source.get("retentionPeriod")
                }
                
                # Count categories
                category = metric_info["category"]
                categories[category] = categories.get(category, 0) + 1
                
                formatted_sources.append(metric_info)
            
            # Sort sources by name for consistent output
            formatted_sources.sort(key=lambda x: x["name"])
            
            formatted_response = {
                "metric_sources": formatted_sources,
                "total_count": len(formatted_sources),
                "filter_applied": filter_pattern is not None,
                "filter_pattern": filter_pattern,
                "categories": categories,
                "limit_applied": limit,
                "summary": {
                    "total_sources": len(formatted_sources),
                    "unique_categories": len(categories),
                    "most_common_category": max(categories.items(), key=lambda x: x[1])[0] if categories else None
                }
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Metric sources listing validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Metric sources listing API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error listing metric sources: {e}")
            raise APIError(f"Failed to list metric sources: {str(e)}")
    
    def _validate_metrics_query(self, query: str) -> None:
        """Validate metrics query syntax.
        
        Args:
            query: Metrics query string to validate
            
        Raises:
            ValidationError: If query syntax is invalid
        """
        # Basic validation for metrics query syntax
        query = query.strip()
        
        if len(query) == 0:
            raise ValidationError("Query cannot be empty")
        
        if len(query) > 10000:
            raise ValidationError("Query is too long (max 10000 characters)")
        
        # Check for basic metrics query patterns
        # Metrics queries typically contain metric selectors and aggregation functions
        
        # Check for potentially dangerous patterns
        dangerous_patterns = [
            r';\s*drop\s+',  # SQL injection attempts
            r';\s*delete\s+',
            r';\s*update\s+',
            r'<script',  # XSS attempts
            r'javascript:',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                raise ValidationError("Query contains potentially dangerous content")
        
        # Validate basic metrics query structure
        # Should contain at least a metric selector
        if not re.search(r'\w+\s*[{=]', query):
            logger.warning(f"Query may not contain valid metric selector: {query[:50]}...")
    
    def _calculate_time_range_ms(self, from_time: str, to_time: str) -> int:
        """Calculate time range in milliseconds.
        
        Args:
            from_time: Start time string
            to_time: End time string
            
        Returns:
            Time range in milliseconds
        """
        try:
            # This is a simplified calculation
            # In a real implementation, you'd parse the time strings properly
            # For now, return a default value
            return 3600000  # 1 hour in milliseconds
        except Exception:
            return 0
    
    async def get_metric_metadata(
        self,
        metric_name: str
    ) -> Dict[str, Any]:
        """Get detailed metadata for a specific metric.
        
        This tool retrieves comprehensive metadata about a specific metric
        including its dimensions, units, and usage statistics.
        
        Args:
            metric_name: Name of the metric to get metadata for
            
        Returns:
            Dict containing metric metadata:
            {
                "name": str,
                "description": str,
                "dimensions": List[str],
                "unit": str,
                "type": str,
                "retention_period": str,
                "sample_queries": List[str]
            }
            
        Raises:
            ValidationError: If metric_name is invalid
            APIError: If metadata retrieval fails
        """
        try:
            if not metric_name or not isinstance(metric_name, str):
                raise ValidationError("Metric name must be a non-empty string")
            
            logger.info(f"Getting metadata for metric: {metric_name}")
            
            # Get metric metadata from API
            metadata_response = await self.api_client.get_metric_metadata(metric_name)
            
            # Format metadata response
            metadata = metadata_response.get("metadata", {})
            
            # Generate sample queries based on metric type and dimensions
            sample_queries = self._generate_sample_queries(metric_name, metadata)
            
            formatted_response = {
                "name": metadata.get("name", metric_name),
                "description": metadata.get("description", ""),
                "dimensions": metadata.get("dimensions", []),
                "unit": metadata.get("unit", ""),
                "type": metadata.get("type", "gauge"),
                "category": metadata.get("category", ""),
                "retention_period": metadata.get("retentionPeriod", ""),
                "last_updated": metadata.get("lastUpdated"),
                "sample_rate": metadata.get("sampleRate"),
                "cardinality": metadata.get("cardinality", 0),
                "sample_queries": sample_queries,
                "usage_tips": self._generate_usage_tips(metadata)
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Metric metadata validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Metric metadata API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting metric metadata: {e}")
            raise APIError(f"Failed to get metric metadata: {str(e)}")
    
    # Compatibility alias for reference implementation
    async def list_metrics(
        self,
        source_category: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """List metrics for source category (alias for list_metric_sources).
        
        This tool provides backward compatibility with the reference TypeScript implementation
        by offering the same interface for listing metrics by source category.
        
        Args:
            source_category: Source category to list metrics for
            limit: Maximum number of metrics to return (1-1000)
            
        Returns:
            Dict containing metrics list in reference-compatible format:
            {
                "metrics": List[str],
                "source_category": str,
                "total_count": int,
                "limit": int
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If metrics listing fails
        """
        try:
            if not source_category or not isinstance(source_category, str):
                raise ValidationError("Source category must be a non-empty string")
            
            logger.info(f"Listing metrics for source category: {source_category}")
            
            # Create a filter pattern based on source category
            # This is a simplified approach - in practice, you might need to query
            # metrics that are associated with the specific source category
            filter_pattern = f".*{re.escape(source_category)}.*"
            
            # Use the existing list_metric_sources method
            sources_result = await self.list_metric_sources(
                filter_pattern=filter_pattern,
                limit=limit
            )
            
            # Extract metric names for reference compatibility
            metric_names = [
                source["name"] for source in sources_result.get("metric_sources", [])
                if source.get("name")
            ]
            
            # Format response for reference compatibility
            result = {
                "metrics": metric_names,
                "source_category": source_category,
                "total_count": len(metric_names),
                "limit": limit,
                "filter_pattern_used": filter_pattern,
                "categories": sources_result.get("categories", {}),
                "summary": sources_result.get("summary", {})
            }
            
            logger.info(f"Found {len(metric_names)} metrics for source category {source_category}")
            return result
            
        except ValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Failed to list metrics for source category: {e}")
            raise APIError(f"Metrics listing failed: {str(e)}")
    
    def _generate_sample_queries(self, metric_name: str, metadata: Dict[str, Any]) -> List[str]:
        """Generate sample queries for a metric.
        
        Args:
            metric_name: Name of the metric
            metadata: Metric metadata
            
        Returns:
            List of sample query strings
        """
        queries = []
        dimensions = metadata.get("dimensions", [])
        metric_type = metadata.get("type", "gauge")
        
        # Basic query
        queries.append(f"{metric_name}")
        
        # Query with time aggregation
        if metric_type in ["counter", "gauge"]:
            queries.append(f"{metric_name} | avg by (_sourceHost)")
        
        # Query with dimension filtering
        if dimensions:
            first_dim = dimensions[0]
            queries.append(f'{metric_name}{{"{first_dim}"="*"}}')
        
        # Query with rate calculation for counters
        if metric_type == "counter":
            queries.append(f"rate({metric_name}[5m])")
        
        return queries[:5]  # Limit to 5 sample queries
    
    def _generate_usage_tips(self, metadata: Dict[str, Any]) -> List[str]:
        """Generate usage tips for a metric.
        
        Args:
            metadata: Metric metadata
            
        Returns:
            List of usage tip strings
        """
        tips = []
        metric_type = metadata.get("type", "gauge")
        dimensions = metadata.get("dimensions", [])
        
        if metric_type == "counter":
            tips.append("Use rate() function to calculate per-second rate for counter metrics")
        
        if metric_type == "gauge":
            tips.append("Use aggregation functions like avg(), max(), min() for gauge metrics")
        
        if dimensions:
            tips.append(f"Available dimensions for filtering: {', '.join(dimensions[:3])}")
        
        if metadata.get("unit"):
            tips.append(f"Metric values are in {metadata.get('unit')} units")
        
        return tips
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for metrics operations.
        
        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "query_metrics",
                "description": "Execute metrics query and return time-series data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Metrics query using Sumo Logic metrics query language"
                        },
                        "from_time": {
                            "type": "string",
                            "description": "Start time (ISO format, relative time like '-1h', or epoch)"
                        },
                        "to_time": {
                            "type": "string",
                            "description": "End time (ISO format, relative time like 'now', or epoch)"
                        },
                        "quantization": {
                            "type": "integer",
                            "description": "Time bucket size in seconds for data aggregation",
                            "minimum": 1
                        },
                        "rollup": {
                            "type": "string",
                            "description": "Rollup type for aggregation",
                            "enum": ["Avg", "Sum", "Min", "Max", "Count", "None"]
                        },
                        "max_data_points": {
                            "type": "integer",
                            "description": "Maximum number of data points to return (1-10000)",
                            "minimum": 1,
                            "maximum": 10000,
                            "default": 1000
                        }
                    },
                    "required": ["query", "from_time", "to_time"]
                }
            },
            {
                "name": "list_metric_sources",
                "description": "List available metric sources for discovery",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter_pattern": {
                            "type": "string",
                            "description": "Optional regex pattern to filter metric names"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of metric sources to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "get_metric_metadata",
                "description": "Get detailed metadata for a specific metric",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "metric_name": {
                            "type": "string",
                            "description": "Name of the metric to get metadata for"
                        }
                    },
                    "required": ["metric_name"]
                }
            },
            # Compatibility alias for reference implementation
            {
                "name": "list_metrics",
                "description": "List metrics for source category (alias for list_metric_sources with reference compatibility)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_category": {
                            "type": "string",
                            "description": "Source category to list metrics for"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of metrics to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        }
                    },
                    "required": ["source_category"]
                }
            }
        ]