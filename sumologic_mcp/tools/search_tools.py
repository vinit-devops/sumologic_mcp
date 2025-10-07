"""
Search tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic search operations including
log searching, job monitoring, and result retrieval with pagination support.
"""

import asyncio
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timedelta

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError
from ..models.config import SearchRequest
from ..models.responses import SearchResult
from ..time_utils import TimeParser, VMwareQueryPatterns

logger = logging.getLogger(__name__)


class SearchTools:
    """MCP tools for Sumo Logic search operations."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize SearchTools with API client.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
    
    async def search_logs(
        self,
        query: str,
        from_time: str,
        to_time: str,
        limit: int = 100,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """Search Sumo Logic logs with specified parameters.
        
        This tool executes a log search query against Sumo Logic's Search API
        and returns formatted results. Supports both synchronous and asynchronous
        search execution based on query complexity.
        
        Args:
            query: Search query string using Sumo Logic query language
            from_time: Start time (ISO format, relative time, or epoch)
            to_time: End time (ISO format, relative time, or epoch)
            limit: Maximum number of results to return (1-10000)
            timeout: Maximum time to wait for search completion in seconds
            
        Returns:
            Dict containing search results with metadata:
            {
                "job_id": str,
                "status": str,
                "message_count": int,
                "record_count": int,
                "results": List[Dict],
                "fields": List[str],
                "execution_time_ms": int
            }
            
        Raises:
            ValidationError: If search parameters are invalid
            APIError: If search execution fails
        """
        try:
            # Validate search parameters
            search_request = SearchRequest(
                query=query,
                from_time=from_time,
                to_time=to_time,
                limit=limit
            )
            
            logger.info(f"Starting log search with query: {query[:100]}...")
            
            # Execute search and get job ID
            search_response = await self.api_client.search_logs(
                query=search_request.query,
                from_time=search_request.from_time,
                to_time=search_request.to_time,
                limit=search_request.limit
            )
            
            job_id = search_response.get("id")
            if not job_id:
                raise APIError("Search job ID not returned from API")
            
            # Monitor search job until completion or timeout
            start_time = datetime.now()
            while True:
                status_response = await self.get_search_job_status(job_id)
                status = status_response.get("status", "").lower()
                
                if status == "done gathering results":
                    break
                elif status in ["cancelled", "force paused"]:
                    raise APIError(f"Search job {job_id} was {status}")
                elif status == "not started":
                    raise APIError(f"Search job {job_id} failed to start")
                
                # Check timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    # Cancel the job if it's still running
                    try:
                        await self.api_client.cancel_search_job(job_id)
                    except Exception as e:
                        logger.warning(f"Failed to cancel timed-out search job {job_id}: {e}")
                    raise APIError(f"Search job {job_id} timed out after {timeout} seconds")
                
                # Wait before next status check
                await asyncio.sleep(2)
            
            # Get search results
            results_response = await self.get_search_results(job_id, limit=limit)
            
            # Format response
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            return {
                "job_id": job_id,
                "status": "completed",
                "message_count": results_response.get("message_count", 0),
                "record_count": results_response.get("record_count", 0),
                "results": results_response.get("results", []),
                "fields": results_response.get("fields", []),
                "execution_time_ms": execution_time,
                "query": query,
                "from_time": from_time,
                "to_time": to_time
            }
            
        except ValidationError as e:
            logger.error(f"Search parameter validation failed: {e}")
            raise ValidationError(f"Invalid search parameters: {e}")
        except APIError as e:
            logger.error(f"Search API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
            raise APIError(f"Search operation failed: {str(e)}")
    
    async def get_search_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of running search job.
        
        This tool monitors the status of an asynchronous search job,
        providing real-time updates on search progress and completion.
        
        Args:
            job_id: Unique identifier for the search job
            
        Returns:
            Dict containing job status information:
            {
                "job_id": str,
                "status": str,
                "message_count": int,
                "record_count": int,
                "pending_errors": List[str],
                "pending_warnings": List[str],
                "histogram_buckets": List[Dict]
            }
            
        Raises:
            ValidationError: If job_id is invalid
            APIError: If status retrieval fails
        """
        try:
            if not job_id or not isinstance(job_id, str):
                raise ValidationError("Job ID must be a non-empty string")
            
            logger.debug(f"Getting status for search job: {job_id}")
            
            status_response = await self.api_client.get_search_job_status(job_id)
            
            # Format and validate response
            formatted_response = {
                "job_id": job_id,
                "status": status_response.get("state", "unknown"),
                "message_count": status_response.get("messageCount", 0),
                "record_count": status_response.get("recordCount", 0),
                "pending_errors": status_response.get("pendingErrors", []),
                "pending_warnings": status_response.get("pendingWarnings", []),
                "histogram_buckets": status_response.get("histogramBuckets", [])
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Job status validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Job status API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting job status: {e}")
            raise APIError(f"Failed to get job status: {str(e)}")
    
    async def get_search_results(
        self,
        job_id: str,
        offset: int = 0,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Retrieve results from completed search job with pagination.
        
        This tool retrieves search results from a completed job with support
        for pagination to handle large result sets efficiently.
        
        Args:
            job_id: Unique identifier for the completed search job
            offset: Starting position for result retrieval (0-based)
            limit: Maximum number of results to return (1-10000)
            
        Returns:
            Dict containing paginated search results:
            {
                "job_id": str,
                "results": List[Dict],
                "fields": List[str],
                "message_count": int,
                "record_count": int,
                "offset": int,
                "limit": int,
                "has_more": bool
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If result retrieval fails
        """
        try:
            # Validate parameters
            if not job_id or not isinstance(job_id, str):
                raise ValidationError("Job ID must be a non-empty string")
            
            if offset < 0:
                raise ValidationError("Offset must be non-negative")
            
            if limit < 1 or limit > 10000:
                raise ValidationError("Limit must be between 1 and 10000")
            
            logger.debug(f"Getting results for job {job_id}, offset={offset}, limit={limit}")
            
            # Get search results from API
            results_response = await self.api_client.get_search_results(
                job_id=job_id,
                offset=offset,
                limit=limit
            )
            
            # Extract and format results
            messages = results_response.get("messages", [])
            records = results_response.get("records", [])
            fields = results_response.get("fields", [])
            
            # Combine messages and records for unified result format
            all_results = []
            
            # Add messages (log entries)
            for message in messages:
                result_entry = {
                    "type": "message",
                    "timestamp": message.get("timestamp"),
                    "raw": message.get("raw", ""),
                    "fields": message.get("map", {})
                }
                all_results.append(result_entry)
            
            # Add records (aggregated data)
            for record in records:
                result_entry = {
                    "type": "record",
                    "fields": record.get("map", {})
                }
                all_results.append(result_entry)
            
            # Get total counts from job status
            status_response = await self.get_search_job_status(job_id)
            total_message_count = status_response.get("message_count", 0)
            total_record_count = status_response.get("record_count", 0)
            
            # Determine if there are more results
            total_results = len(all_results)
            has_more = (offset + total_results) < (total_message_count + total_record_count)
            
            formatted_response = {
                "job_id": job_id,
                "results": all_results,
                "fields": [field.get("name", "") for field in fields],
                "message_count": total_message_count,
                "record_count": total_record_count,
                "offset": offset,
                "limit": limit,
                "returned_count": total_results,
                "has_more": has_more
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Result retrieval validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Result retrieval API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error retrieving results: {e}")
            raise APIError(f"Failed to retrieve search results: {str(e)}")
    
    # Compatibility tools for reference implementation parity
    
    async def execute_query(
        self,
        query: str,
        from_time: str = "-1h",
        to_time: str = "now",
        limit: int = 1000
    ) -> Dict[str, Any]:
        """Execute query (alias for search_logs with reference-compatible parameters).
        
        This tool provides backward compatibility with the reference TypeScript implementation
        by offering the same interface and parameter defaults.
        
        Args:
            query: Search query string using Sumo Logic query language
            from_time: Start time (relative format like '-1h', ISO format, or epoch)
            to_time: End time (relative format like 'now', ISO format, or epoch)
            limit: Maximum number of results to return (1-10000)
            
        Returns:
            Dict containing search results in reference-compatible format:
            {
                "job_id": str,
                "status": str,
                "results": List[Dict],
                "total_count": int,
                "execution_time_ms": int,
                "query": str,
                "from_time": str,
                "to_time": str
            }
            
        Raises:
            ValidationError: If search parameters are invalid
            APIError: If search execution fails
        """
        try:
            logger.info(f"Executing query (reference compatibility): {query[:100]}...")
            
            # Use the existing search_logs method with reference defaults
            result = await self.search_logs(
                query=query,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                timeout=300  # Reference implementation default
            )
            
            # Format response for reference compatibility
            return {
                "job_id": result.get("job_id"),
                "status": result.get("status"),
                "results": result.get("results", []),
                "total_count": result.get("message_count", 0) + result.get("record_count", 0),
                "execution_time_ms": result.get("execution_time_ms", 0),
                "query": query,
                "from_time": from_time,
                "to_time": to_time,
                "fields": result.get("fields", [])
            }
            
        except Exception as e:
            logger.error(f"Execute query failed: {e}")
            raise
    
    async def list_source_categories(self, pattern: Optional[str] = None) -> Dict[str, Any]:
        """List available source categories with optional pattern filtering.
        
        This tool discovers source categories by querying collectors and their sources,
        providing filtering capabilities for source category exploration.
        
        Args:
            pattern: Optional pattern to filter source categories (supports wildcards)
            
        Returns:
            Dict containing source categories:
            {
                "source_categories": List[str],
                "total_count": int,
                "pattern": str,
                "collectors_scanned": int
            }
            
        Raises:
            APIError: If source category discovery fails
        """
        try:
            logger.info(f"Listing source categories with pattern: {pattern}")
            
            # Get all collectors to discover source categories
            collectors_response = await self.api_client.list_collectors(limit=1000)
            collectors = collectors_response.get("data", [])
            
            source_categories = set()
            collectors_scanned = 0
            
            # Scan each collector for sources and their categories
            for collector in collectors:
                try:
                    collector_id = collector.get("id")
                    if not collector_id:
                        continue
                    
                    # Get sources for this collector
                    sources_response = await self.api_client.list_sources(collector_id)
                    sources = sources_response.get("sources", [])
                    
                    collectors_scanned += 1
                    
                    # Extract source categories
                    for source in sources:
                        category = source.get("category")
                        if category:
                            source_categories.add(category)
                            
                except Exception as e:
                    logger.warning(f"Failed to get sources for collector {collector_id}: {e}")
                    continue
            
            # Convert to sorted list
            categories_list = sorted(list(source_categories))
            
            # Apply pattern filtering if provided
            if pattern:
                import fnmatch
                categories_list = [
                    cat for cat in categories_list 
                    if fnmatch.fnmatch(cat.lower(), pattern.lower())
                ]
            
            result = {
                "source_categories": categories_list,
                "total_count": len(categories_list),
                "pattern": pattern,
                "collectors_scanned": collectors_scanned
            }
            
            logger.info(f"Found {len(categories_list)} source categories")
            return result
            
        except Exception as e:
            logger.error(f"Failed to list source categories: {e}")
            raise APIError(f"Source category discovery failed: {str(e)}")
    
    async def validate_query_syntax(self, query: str) -> Dict[str, Any]:
        """Validate query syntax without execution using dry-run approach.
        
        This tool validates Sumo Logic query syntax by attempting to start a search
        job with a very short time range and immediately cancelling it, allowing
        syntax validation without consuming significant resources.
        
        Args:
            query: Search query string to validate
            
        Returns:
            Dict containing validation results:
            {
                "valid": bool,
                "query": str,
                "errors": List[str],
                "warnings": List[str],
                "syntax_check": str
            }
            
        Raises:
            ValidationError: If query parameter is invalid
            APIError: If validation process fails
        """
        try:
            if not query or not query.strip():
                raise ValidationError("Query cannot be empty")
            
            query = query.strip()
            logger.info(f"Validating query syntax: {query[:100]}...")
            
            # Use a very short time range for syntax validation
            validation_from = "-1m"  # Last 1 minute
            validation_to = "now"
            
            try:
                # Attempt to start search job for syntax validation
                search_response = await self.api_client.search_logs(
                    query=query,
                    from_time=validation_from,
                    to_time=validation_to,
                    limit=1  # Minimal limit
                )
                
                job_id = search_response.get("id")
                
                # Immediately cancel the job to avoid resource consumption
                if job_id:
                    try:
                        await self.api_client.cancel_search_job(job_id)
                    except Exception as cancel_error:
                        logger.warning(f"Failed to cancel validation job {job_id}: {cancel_error}")
                
                # If we got here, syntax is valid
                return {
                    "valid": True,
                    "query": query,
                    "errors": [],
                    "warnings": [],
                    "syntax_check": "passed",
                    "validation_job_id": job_id
                }
                
            except APIError as api_error:
                # Parse error details from API response
                errors = []
                warnings = []
                
                # Check if this is a syntax error
                if api_error.status_code == 400:
                    error_message = api_error.message or "Unknown syntax error"
                    errors.append(error_message)
                    
                    return {
                        "valid": False,
                        "query": query,
                        "errors": errors,
                        "warnings": warnings,
                        "syntax_check": "failed",
                        "error_details": {
                            "status_code": api_error.status_code,
                            "message": error_message
                        }
                    }
                else:
                    # Re-raise non-syntax errors
                    raise
                    
        except ValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Query validation failed: {e}")
            raise APIError(f"Query syntax validation failed: {str(e)}")
    
    async def get_sample_data(
        self,
        source_category: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get sample data from source category with field analysis.
        
        This tool retrieves sample log entries from a specified source category
        and analyzes the field structure to help users understand the data format.
        
        Args:
            source_category: Source category to sample data from
            limit: Maximum number of sample records to return (1-100)
            
        Returns:
            Dict containing sample data and analysis:
            {
                "source_category": str,
                "sample_count": int,
                "samples": List[Dict],
                "field_analysis": Dict,
                "common_fields": List[str],
                "data_types": Dict[str, str],
                "time_range": Dict
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If sample data retrieval fails
        """
        try:
            if not source_category or not source_category.strip():
                raise ValidationError("Source category cannot be empty")
            
            if limit < 1 or limit > 100:
                raise ValidationError("Limit must be between 1 and 100")
            
            source_category = source_category.strip()
            logger.info(f"Getting sample data from source category: {source_category}")
            
            # Build query to get sample data from the source category
            sample_query = f'_sourceCategory="{source_category}"'
            
            # Use recent time range for sampling
            from_time = "-1h"
            to_time = "now"
            
            # Execute search to get sample data
            search_result = await self.search_logs(
                query=sample_query,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                timeout=60  # Shorter timeout for sampling
            )
            
            samples = search_result.get("results", [])
            
            # Analyze field structure
            field_analysis = self._analyze_sample_fields(samples)
            
            result = {
                "source_category": source_category,
                "sample_count": len(samples),
                "samples": samples,
                "field_analysis": field_analysis,
                "common_fields": field_analysis.get("common_fields", []),
                "data_types": field_analysis.get("data_types", {}),
                "time_range": {
                    "from": from_time,
                    "to": to_time
                },
                "query_used": sample_query
            }
            
            logger.info(f"Retrieved {len(samples)} sample records from {source_category}")
            return result
            
        except ValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Failed to get sample data: {e}")
            raise APIError(f"Sample data retrieval failed: {str(e)}")
    
    async def explore_vmware_metrics(
        self,
        source_category: str = "otel/vmware"
    ) -> Dict[str, Any]:
        """Explore VMware metrics and resource attributes.
        
        This tool provides specialized exploration of VMware metrics, discovering
        available metrics, resource attributes, and common query patterns for
        VMware monitoring data using enhanced VMware-specific functionality.
        
        Args:
            source_category: VMware source category to explore (default: "otel/vmware")
            
        Returns:
            Dict containing VMware metrics exploration:
            {
                "source_category": str,
                "metrics_discovered": List[str],
                "resource_attributes": List[str],
                "query_patterns": Dict[str, List[Dict]],
                "sample_metrics": List[Dict],
                "exploration_summary": Dict,
                "time_examples": List[Dict]
            }
            
        Raises:
            APIError: If VMware metrics exploration fails
        """
        try:
            logger.info(f"Exploring VMware metrics in source category: {source_category}")
            
            # Use VMware-specific discovery queries
            metrics_discovery_query = VMwareQueryPatterns.get_metric_discovery_query(source_category)
            resource_discovery_query = VMwareQueryPatterns.get_resource_discovery_query(source_category)
            
            # Get recent VMware metrics data using relative time parsing
            from_time = "-1h"
            to_time = "now"
            
            # Validate time range using TimeParser
            start_dt, end_dt = TimeParser.validate_time_range(from_time, to_time)
            
            # Execute metrics discovery query
            metrics_result = await self.search_logs(
                query=metrics_discovery_query,
                from_time=from_time,
                to_time=to_time,
                limit=100,
                timeout=120
            )
            
            # Extract discovered metrics
            metrics_discovered = []
            sample_metrics = []
            
            for result in metrics_result.get("results", []):
                if result.get("type") == "record":
                    fields = result.get("fields", {})
                    metric_name = fields.get("metric_name")
                    if metric_name:
                        metrics_discovered.append(metric_name)
                        sample_metrics.append({
                            "metric_name": metric_name,
                            "count": fields.get("_count", 0)
                        })
            
            # Execute resource attributes discovery
            attributes_result = await self.search_logs(
                query=resource_discovery_query,
                from_time=from_time,
                to_time=to_time,
                limit=50,
                timeout=60
            )
            
            # Extract resource attributes
            resource_attributes = set()
            for result in attributes_result.get("results", []):
                if result.get("type") == "record":
                    fields = result.get("fields", {})
                    key_name = fields.get("_key")
                    if key_name and any(attr in key_name.lower() for attr in [
                        'vm', 'host', 'cluster', 'datacenter', 'resource',
                        'vcenter', 'esxi', 'instance', 'name', 'uuid'
                    ]):
                        resource_attributes.add(key_name)
            
            # Get comprehensive VMware query patterns
            query_patterns = VMwareQueryPatterns.get_all_query_patterns(source_category)
            
            # Add time parsing examples
            time_examples = TimeParser.get_relative_time_examples()
            
            # Enhanced exploration summary
            exploration_summary = {
                "total_metrics": len(metrics_discovered),
                "total_attributes": len(resource_attributes),
                "time_range_explored": f"{from_time} to {to_time}",
                "parsed_start_time": start_dt.isoformat(),
                "parsed_end_time": end_dt.isoformat(),
                "source_category": source_category,
                "query_categories": list(query_patterns.keys()),
                "vmware_metrics_available": {
                    category: len(VMwareQueryPatterns.VMWARE_METRICS.get(category, []))
                    for category in VMwareQueryPatterns.VMWARE_METRICS.keys()
                }
            }
            
            # Categorize discovered metrics by type
            categorized_metrics = {
                "cpu": [m for m in metrics_discovered if "cpu" in m.lower()],
                "memory": [m for m in metrics_discovered if "memory" in m.lower()],
                "disk": [m for m in metrics_discovered if any(term in m.lower() for term in ["disk", "datastore"])],
                "network": [m for m in metrics_discovered if "network" in m.lower()],
                "other": [m for m in metrics_discovered if not any(term in m.lower() for term in ["cpu", "memory", "disk", "datastore", "network"])]
            }
            
            result = {
                "source_category": source_category,
                "metrics_discovered": sorted(metrics_discovered),
                "categorized_metrics": categorized_metrics,
                "resource_attributes": sorted(list(resource_attributes)),
                "query_patterns": query_patterns,
                "sample_metrics": sample_metrics[:20],  # Limit to top 20
                "exploration_summary": exploration_summary,
                "time_examples": time_examples,
                "vmware_attributes": VMwareQueryPatterns.VMWARE_ATTRIBUTES,
                "recommended_queries": self._get_recommended_vmware_queries(source_category, metrics_discovered)
            }
            
            logger.info(f"VMware exploration complete: {len(metrics_discovered)} metrics, {len(resource_attributes)} attributes")
            return result
            
        except Exception as e:
            logger.error(f"VMware metrics exploration failed: {e}")
            raise APIError(f"VMware metrics exploration failed: {str(e)}")
    
    def _get_recommended_vmware_queries(self, source_category: str, discovered_metrics: List[str]) -> List[Dict[str, str]]:
        """Get recommended queries based on discovered metrics.
        
        Args:
            source_category: VMware source category
            discovered_metrics: List of discovered metric names
            
        Returns:
            List of recommended query dictionaries
        """
        recommendations = []
        
        # Check which metrics are available and recommend appropriate queries
        if any("vm.cpu.usage" in metric for metric in discovered_metrics):
            recommendations.append({
                "name": "VM CPU Performance Analysis",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.cpu.usage.average" | avg by vm.name | sort by _avg desc',
                "description": "Analyze VM CPU performance and identify top consumers"
            })
        
        if any("vm.memory.usage" in metric for metric in discovered_metrics):
            recommendations.append({
                "name": "Memory Pressure Detection",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.memory.usage.average" | where _value > 80',
                "description": "Detect VMs with high memory pressure"
            })
        
        if any("datastore" in metric for metric in discovered_metrics):
            recommendations.append({
                "name": "Storage Capacity Planning",
                "query": f'_sourceCategory="{source_category}" metric_name matches "*datastore*" | timeslice 1h | avg by datastore.name',
                "description": "Monitor datastore usage trends for capacity planning"
            })
        
        if any("host.cpu" in metric for metric in discovered_metrics):
            recommendations.append({
                "name": "Host Resource Utilization",
                "query": f'_sourceCategory="{source_category}" metric_name matches "host.*" | avg by host.name',
                "description": "Monitor ESXi host resource utilization"
            })
        
        return recommendations
    
    def _analyze_sample_fields(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze field structure from sample data.
        
        Args:
            samples: List of sample log entries
            
        Returns:
            Dictionary containing field analysis results
        """
        if not samples:
            return {
                "common_fields": [],
                "data_types": {},
                "field_frequency": {},
                "total_samples": 0
            }
        
        field_counts = {}
        field_types = {}
        
        # Analyze each sample
        for sample in samples:
            fields = sample.get("fields", {})
            
            for field_name, field_value in fields.items():
                # Count field frequency
                field_counts[field_name] = field_counts.get(field_name, 0) + 1
                
                # Determine field type
                if field_name not in field_types:
                    if isinstance(field_value, bool):
                        field_types[field_name] = "boolean"
                    elif isinstance(field_value, int):
                        field_types[field_name] = "integer"
                    elif isinstance(field_value, float):
                        field_types[field_name] = "float"
                    elif isinstance(field_value, str):
                        # Try to detect special string types
                        if field_value.isdigit():
                            field_types[field_name] = "numeric_string"
                        elif "@" in field_value and "." in field_value:
                            field_types[field_name] = "email"
                        elif field_value.startswith("http"):
                            field_types[field_name] = "url"
                        else:
                            field_types[field_name] = "string"
                    else:
                        field_types[field_name] = "object"
        
        # Identify common fields (present in most samples)
        total_samples = len(samples)
        common_threshold = max(1, total_samples * 0.5)  # Present in at least 50% of samples
        
        common_fields = [
            field for field, count in field_counts.items()
            if count >= common_threshold
        ]
        
        return {
            "common_fields": sorted(common_fields),
            "data_types": field_types,
            "field_frequency": field_counts,
            "total_samples": total_samples
        }
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for search operations.
        
        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "search_logs",
                "description": "Search Sumo Logic logs with specified query and time range",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query using Sumo Logic query language"
                        },
                        "from_time": {
                            "type": "string",
                            "description": "Start time (ISO format, relative time like '-1h', or epoch)"
                        },
                        "to_time": {
                            "type": "string",
                            "description": "End time (ISO format, relative time like 'now', or epoch)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-10000)",
                            "minimum": 1,
                            "maximum": 10000,
                            "default": 100
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Maximum time to wait for search completion in seconds",
                            "minimum": 30,
                            "maximum": 3600,
                            "default": 300
                        }
                    },
                    "required": ["query", "from_time", "to_time"]
                }
            },
            {
                "name": "get_search_job_status",
                "description": "Get status of a running search job",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Unique identifier for the search job"
                        }
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "get_search_results",
                "description": "Retrieve results from a completed search job with pagination",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Unique identifier for the completed search job"
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Starting position for result retrieval (0-based)",
                            "minimum": 0,
                            "default": 0
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-10000)",
                            "minimum": 1,
                            "maximum": 10000,
                            "default": 100
                        }
                    },
                    "required": ["job_id"]
                }
            },
            # Compatibility tools for reference implementation parity
            {
                "name": "execute_query",
                "description": "Execute query (alias for search_logs with reference-compatible parameters)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query using Sumo Logic query language"
                        },
                        "from_time": {
                            "type": "string",
                            "description": "Start time (relative format like '-1h', ISO format, or epoch)",
                            "default": "-1h"
                        },
                        "to_time": {
                            "type": "string",
                            "description": "End time (relative format like 'now', ISO format, or epoch)",
                            "default": "now"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-10000)",
                            "minimum": 1,
                            "maximum": 10000,
                            "default": 1000
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_source_categories",
                "description": "List available source categories with optional pattern filtering",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Optional pattern to filter source categories (supports wildcards)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "validate_query_syntax",
                "description": "Validate query syntax without execution using dry-run approach",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string to validate"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_sample_data",
                "description": "Get sample data from source category with field analysis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_category": {
                            "type": "string",
                            "description": "Source category to sample data from"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of sample records to return (1-100)",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 10
                        }
                    },
                    "required": ["source_category"]
                }
            },
            {
                "name": "explore_vmware_metrics",
                "description": "Explore VMware metrics and resource attributes",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_category": {
                            "type": "string",
                            "description": "VMware source category to explore",
                            "default": "otel/vmware"
                        }
                    },
                    "required": []
                }
            }
        ]