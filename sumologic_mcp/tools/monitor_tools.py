"""
Monitor tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic monitor (alert) management
including listing, creating, updating, deleting monitors, and managing monitor
status and alerts with comprehensive configuration validation and error handling.
"""

from typing import Dict, Any, Optional, List, Callable
import logging
import time
from datetime import datetime

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError, RateLimitError, TimeoutError
from ..models.monitor import (
    MonitorConfig,
    MonitorResponse,
    MonitorStatusInfo,
    ActiveAlert,
    MonitorValidationResult,
    MonitorType,
    TriggerType,
    NotificationType,
    MonitorStatus,
    ThresholdType
)
from .monitor_error_handler import (
    MonitorErrorHandler,
    MonitorError,
    MonitorValidationError,
    MonitorNotFoundError,
    MonitorPermissionError,
    MonitorConfigurationError,
    MonitorOperationError,
    validate_monitor_id,
    validate_pagination_params,
    create_monitor_error_context
)

logger = logging.getLogger(__name__)


class MonitorTools:
    """MCP tools for Sumo Logic monitor operations with comprehensive error handling."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize MonitorTools with API client and error handling.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
        
        # Initialize enhanced error handler for monitor operations
        self.error_handler = MonitorErrorHandler("monitor_tools")
        
        logger.info(
            "Initialized MonitorTools with enhanced error handling and resilience patterns",
            extra={
                "api_endpoint": getattr(api_client.config, 'endpoint', 'unknown'),
                "error_handler": "enabled",
                "circuit_breaker": "enabled",
                "retry_logic": "enabled"
            }
        )
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for monitor operations.
        
        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "list_monitors",
                "description": "List all monitors with optional filtering and pagination, including folder-based searches",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter_name": {
                            "type": "string",
                            "description": "Optional name filter with pattern matching support (supports * and ? wildcards)"
                        },
                        "filter_type": {
                            "type": "string",
                            "description": "Optional monitor type filter (logs, metrics, SLI)",
                            "enum": ["logs", "metrics", "SLI"]
                        },
                        "filter_status": {
                            "type": "string",
                            "description": "Optional status filter (enabled, disabled, triggered)",
                            "enum": ["enabled", "disabled", "triggered"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of monitors to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Starting position for pagination (0-based)",
                            "minimum": 0,
                            "default": 0
                        },
                        "include_folders": {
                            "type": "boolean",
                            "description": "Whether to include monitors within folders in search results (default: true)",
                            "default": True
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "search_monitors",
                "description": "Search monitors with advanced search capabilities and relevance scoring",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search_query": {
                            "type": "string",
                            "description": "Search query string to match against monitor fields"
                        },
                        "search_fields": {
                            "type": "array",
                            "description": "Fields to search in (default: name, description, query)",
                            "items": {
                                "type": "string",
                                "enum": ["name", "description", "query"]
                            },
                            "default": ["name", "description", "query"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Starting position for pagination (0-based)",
                            "minimum": 0,
                            "default": 0
                        }
                    },
                    "required": ["search_query"]
                }
            },
            {
                "name": "get_monitor",
                "description": "Get detailed monitor configuration and metadata",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor"
                        }
                    },
                    "required": ["monitor_id"]
                }
            },
            {
                "name": "create_monitor",
                "description": "Create new monitor with specified configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Monitor name (required, max 255 characters)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Monitor description",
                            "default": ""
                        },
                        "type": {
                            "type": "string",
                            "description": "Monitor type",
                            "enum": ["MonitorsLibraryMonitor", "MetricsMonitor", "SliMonitor"],
                            "default": "MonitorsLibraryMonitor"
                        },
                        "query": {
                            "type": "string",
                            "description": "Monitor query string (required)"
                        },
                        "trigger_conditions": {
                            "type": "object",
                            "description": "Trigger conditions for different severity levels",
                            "properties": {
                                "Critical": {"type": "object"},
                                "Warning": {"type": "object"},
                                "MissingData": {"type": "object"}
                            }
                        },
                        "notifications": {
                            "type": "array",
                            "description": "Notification actions",
                            "items": {"type": "object"},
                            "default": []
                        },
                        "is_disabled": {
                            "type": "boolean",
                            "description": "Whether monitor is disabled",
                            "default": False
                        },
                        "evaluation_delay": {
                            "type": "string",
                            "description": "Delay before evaluation (e.g., '5m')",
                            "default": "0m"
                        }
                    },
                    "required": ["name", "query", "trigger_conditions"]
                }
            },
            {
                "name": "update_monitor",
                "description": "Update existing monitor configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor to update"
                        },
                        "name": {
                            "type": "string",
                            "description": "New monitor name (max 255 characters)"
                        },
                        "description": {
                            "type": "string",
                            "description": "New monitor description"
                        },
                        "query": {
                            "type": "string",
                            "description": "New monitor query string"
                        },
                        "trigger_conditions": {
                            "type": "object",
                            "description": "New trigger conditions"
                        },
                        "notifications": {
                            "type": "array",
                            "description": "New notification actions",
                            "items": {"type": "object"}
                        },
                        "is_disabled": {
                            "type": "boolean",
                            "description": "Whether monitor is disabled"
                        },
                        "evaluation_delay": {
                            "type": "string",
                            "description": "New evaluation delay"
                        }
                    },
                    "required": ["monitor_id"]
                }
            },
            {
                "name": "delete_monitor",
                "description": "Delete specified monitor permanently",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor to delete"
                        }
                    },
                    "required": ["monitor_id"]
                }
            },
            {
                "name": "get_monitor_status",
                "description": "Get current status of monitors and active alerts",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Optional monitor ID to get status for specific monitor"
                        },
                        "filter_status": {
                            "type": "string",
                            "description": "Optional status filter (triggered, normal, disabled)",
                            "enum": ["triggered", "normal", "disabled", "unknown"]
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "get_active_alerts",
                "description": "Get all currently active alerts with optional severity filtering",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "description": "Optional severity filter",
                            "enum": ["Critical", "Warning", "MissingData"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of alerts to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "enable_monitor",
                "description": "Enable specified monitor",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor to enable"
                        }
                    },
                    "required": ["monitor_id"]
                }
            },
            {
                "name": "disable_monitor",
                "description": "Disable specified monitor",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor to disable"
                        }
                    },
                    "required": ["monitor_id"]
                }
            },
            {
                "name": "validate_monitor_config",
                "description": "Validate monitor configuration without creating the monitor",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "config": {
                            "type": "object",
                            "description": "Monitor configuration to validate",
                            "properties": {
                                "name": {"type": "string"},
                                "query": {"type": "string"},
                                "trigger_conditions": {"type": "object"},
                                "notifications": {"type": "array"}
                            },
                            "required": ["name", "query", "trigger_conditions"]
                        }
                    },
                    "required": ["config"]
                }
            },
            {
                "name": "get_monitor_history",
                "description": "Get monitor execution history and performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {
                            "type": "string",
                            "description": "Unique identifier for the monitor"
                        },
                        "from_time": {
                            "type": "string",
                            "description": "Start time for history range (ISO format or relative like '-1h')"
                        },
                        "to_time": {
                            "type": "string",
                            "description": "End time for history range (ISO format or relative like 'now')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of history entries to return (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        }
                    },
                    "required": ["monitor_id", "from_time", "to_time"]
                }
            }
        ]
    
    async def list_monitors(
        self,
        filter_name: Optional[str] = None,
        filter_type: Optional[str] = None,
        filter_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_folders: bool = True
    ) -> Dict[str, Any]:
        """List monitors with optional filtering and pagination, including folder-based searches.
        
        Args:
            filter_name: Optional name filter to search for specific monitors
            filter_type: Optional monitor type filter (logs, metrics, SLI)
            filter_status: Optional status filter (enabled, disabled, triggered)
            limit: Maximum number of monitors to return (1-1000)
            offset: Starting position for pagination (0-based)
            include_folders: Whether to include monitors within folders (default: True)
            
        Returns:
            Dictionary containing monitor list with metadata, statistics, and folder information
            
        Raises:
            MonitorValidationError: If parameters are invalid
            MonitorError: If monitor operation fails
            APIError: If API request fails
            RateLimitError: If rate limit is exceeded
        """
        async def _list_monitors_impl():
            # Validate pagination parameters
            validated_limit, validated_offset = await validate_pagination_params(
                limit, offset, "list_monitors"
            )
            
            # Validate filter_type if provided
            if filter_type:
                valid_types = ["logs", "metrics", "SLI"]
                if filter_type not in valid_types:
                    raise MonitorValidationError(
                        f"Invalid filter_type. Must be one of: {', '.join(valid_types)}",
                        field_name="filter_type",
                        field_value=filter_type,
                        context=create_monitor_error_context(
                            "list_monitors",
                            valid_types=valid_types
                        )
                    )
            
            # Validate filter_status if provided
            if filter_status:
                valid_statuses = ["enabled", "disabled", "triggered"]
                if filter_status not in valid_statuses:
                    raise MonitorValidationError(
                        f"Invalid filter_status. Must be one of: {', '.join(valid_statuses)}",
                        field_name="filter_status",
                        field_value=filter_status,
                        context=create_monitor_error_context(
                            "list_monitors",
                            valid_statuses=valid_statuses
                        )
                    )
            
            # Call API client to get monitors with rate limiting and retry logic
            try:
                api_response = await self.api_client.list_monitors(
                    limit=validated_limit,
                    offset=validated_offset,
                    filter_name=filter_name,
                    filter_type=filter_type,
                    filter_status=filter_status,
                    include_folders=include_folders
                )
            except RateLimitError as e:
                # Add monitor-specific context to rate limit error
                raise RateLimitError(
                    f"Rate limit exceeded while listing monitors: {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "list_monitors",
                        filters={
                            "name": filter_name,
                            "type": filter_type,
                            "status": filter_status
                        }
                    )
                ) from e
            
            # Extract monitors from response
            monitors = api_response.get("data", [])
            total_count = api_response.get("total", len(monitors))
            
            # Apply client-side filtering if needed (for more complex filtering)
            try:
                filtered_monitors = self._apply_client_side_filters(
                    monitors, filter_name, filter_type, filter_status
                )
            except Exception as e:
                raise MonitorError(
                    f"Failed to apply client-side filters: {str(e)}",
                    operation="list_monitors",
                    context=create_monitor_error_context(
                        "list_monitors",
                        filter_error=str(e),
                        monitor_count=len(monitors)
                    )
                ) from e
            
            # Calculate statistics safely including folder information
            try:
                statistics = self._calculate_monitor_statistics(filtered_monitors)
                folder_statistics = self._calculate_folder_statistics(filtered_monitors)
            except Exception as e:
                logger.warning(
                    "Failed to calculate monitor statistics, using defaults",
                    extra={"error": str(e), "monitor_count": len(filtered_monitors)}
                )
                statistics = {"total": len(filtered_monitors), "by_type": {}, "by_status": {}}
                folder_statistics = {"folders_found": 0, "monitors_in_folders": 0, "root_level_monitors": 0}
            
            # Enhance monitors with folder display information
            enhanced_monitors = self._enhance_monitors_with_folder_info(filtered_monitors)
            
            # Format response with metadata, statistics, and folder information
            response = {
                "success": True,
                "monitors": enhanced_monitors,
                "metadata": {
                    "total_count": total_count,
                    "returned_count": len(enhanced_monitors),
                    "offset": validated_offset,
                    "limit": validated_limit,
                    "has_more": (validated_offset + len(enhanced_monitors)) < total_count
                },
                "statistics": statistics,
                "folder_statistics": folder_statistics,
                "folder_info": api_response.get("folder_info", {}),
                "filters_applied": {
                    "name": filter_name,
                    "type": filter_type,
                    "status": filter_status,
                    "include_folders": include_folders
                }
            }
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "list_monitors",
            _list_monitors_impl,
            timeout_override=30.0  # List operations may take longer with large datasets
        )
    
    def _apply_client_side_filters(
        self,
        monitors: List[Dict[str, Any]],
        filter_name: Optional[str],
        filter_type: Optional[str],
        filter_status: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Apply client-side filtering for more complex filter logic.
        
        Args:
            monitors: List of monitor dictionaries
            filter_name: Name filter pattern
            filter_type: Type filter
            filter_status: Status filter
            
        Returns:
            Filtered list of monitors
        """
        filtered = monitors
        
        # Apply name filtering with pattern matching
        if filter_name:
            filtered = self._filter_by_name_pattern(filtered, filter_name)
        
        # Apply type filtering (convert from user-friendly to API format)
        if filter_type:
            filtered = self._filter_by_monitor_type(filtered, filter_type)
        
        # Apply status filtering
        if filter_status:
            filtered = self._filter_by_status(filtered, filter_status)
        
        return filtered
    
    def _filter_by_name_pattern(
        self,
        monitors: List[Dict[str, Any]],
        name_pattern: str
    ) -> List[Dict[str, Any]]:
        """Filter monitors by name pattern with advanced matching.
        
        Args:
            monitors: List of monitor dictionaries
            name_pattern: Name pattern to match (supports wildcards and regex-like patterns)
            
        Returns:
            Filtered list of monitors
        """
        import re
        
        # Convert simple wildcards to regex if needed
        if '*' in name_pattern or '?' in name_pattern:
            # Convert shell-style wildcards to regex
            regex_pattern = name_pattern.replace('*', '.*').replace('?', '.')
            try:
                compiled_pattern = re.compile(regex_pattern, re.IGNORECASE)
                return [
                    monitor for monitor in monitors
                    if compiled_pattern.search(monitor.get("name", ""))
                ]
            except re.error:
                # Fall back to simple substring matching if regex is invalid
                logger.warning(f"Invalid regex pattern '{name_pattern}', falling back to substring matching")
        
        # Simple case-insensitive substring matching
        filter_name_lower = name_pattern.lower()
        return [
            monitor for monitor in monitors
            if filter_name_lower in monitor.get("name", "").lower()
        ]
    
    def _filter_by_monitor_type(
        self,
        monitors: List[Dict[str, Any]],
        monitor_type: str
    ) -> List[Dict[str, Any]]:
        """Filter monitors by type with support for multiple formats.
        
        Args:
            monitors: List of monitor dictionaries
            monitor_type: Monitor type filter (logs, metrics, SLI, or API format)
            
        Returns:
            Filtered list of monitors
        """
        # Type mapping from user-friendly to API format
        type_mapping = {
            "logs": "MonitorsLibraryMonitor",
            "metrics": "MetricsMonitor",
            "SLI": "SliMonitor",
            "sli": "SliMonitor"  # Case insensitive
        }
        
        # Support both user-friendly and API format
        api_type = type_mapping.get(monitor_type.lower(), monitor_type)
        
        return [
            monitor for monitor in monitors
            if monitor.get("monitorType") == api_type
        ]
    
    def _filter_by_status(
        self,
        monitors: List[Dict[str, Any]],
        status_filter: str
    ) -> List[Dict[str, Any]]:
        """Filter monitors by status.
        
        Args:
            monitors: List of monitor dictionaries
            status_filter: Status filter (enabled, disabled, triggered)
            
        Returns:
            Filtered list of monitors
        """
        if status_filter == "enabled":
            return [
                monitor for monitor in monitors
                if not monitor.get("isDisabled", False)
            ]
        elif status_filter == "disabled":
            return [
                monitor for monitor in monitors
                if monitor.get("isDisabled", False)
            ]
        elif status_filter == "triggered":
            # For triggered status, we would need to make additional API calls
            # to get the current status of each monitor. For now, log a warning
            # and return all monitors
            logger.warning(
                "Triggered status filtering requires additional API calls to get monitor status. "
                "Consider using get_monitor_status or get_active_alerts for real-time status information."
            )
            return monitors
        else:
            logger.warning(f"Unknown status filter '{status_filter}', returning all monitors")
            return monitors
    
    def _calculate_folder_statistics(self, monitors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate folder-related statistics from monitor list.
        
        Args:
            monitors: List of monitor dictionaries
            
        Returns:
            Dictionary containing folder statistics
        """
        folder_count = 0
        monitors_in_folders = 0
        root_level_monitors = 0
        folder_paths = set()
        
        for monitor in monitors:
            content_type = monitor.get("contentType", "")
            folder_path = monitor.get("folder_path", "")
            
            if content_type == "MonitorsLibraryFolder":
                folder_count += 1
                if folder_path:
                    folder_paths.add(folder_path)
            elif content_type == "MonitorsLibraryMonitor":
                if folder_path and folder_path != "/" and not folder_path.startswith("/unknown"):
                    monitors_in_folders += 1
                    # Extract parent folder path
                    parent_path = "/".join(folder_path.split("/")[:-1]) or "/"
                    folder_paths.add(parent_path)
                else:
                    root_level_monitors += 1
        
        return {
            "folders_found": folder_count,
            "monitors_in_folders": monitors_in_folders,
            "root_level_monitors": root_level_monitors,
            "unique_folder_paths": len(folder_paths),
            "folder_paths": sorted(list(folder_paths))
        }
    
    def _enhance_monitors_with_folder_info(self, monitors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enhance monitor objects with folder display information.
        
        Args:
            monitors: List of monitor dictionaries
            
        Returns:
            Enhanced list of monitors with folder display information
        """
        enhanced_monitors = []
        
        for monitor in monitors:
            enhanced_monitor = monitor.copy()
            content_type = monitor.get("contentType", "")
            folder_path = monitor.get("folder_path", "")
            
            # Add display information
            enhanced_monitor["display_info"] = {
                "is_folder": content_type == "MonitorsLibraryFolder",
                "is_monitor": content_type == "MonitorsLibraryMonitor",
                "folder_path": folder_path,
                "is_in_folder": bool(folder_path and folder_path != "/" and not folder_path.startswith("/unknown")),
                "parent_folder_id": monitor.get("parent_folder_id"),
                "display_name": self._format_display_name(monitor)
            }
            
            # Add folder breadcrumb for better navigation
            if folder_path and folder_path != "/":
                path_parts = [part for part in folder_path.split("/") if part]
                enhanced_monitor["display_info"]["breadcrumb"] = " > ".join(path_parts)
            else:
                enhanced_monitor["display_info"]["breadcrumb"] = "Root"
            
            enhanced_monitors.append(enhanced_monitor)
        
        return enhanced_monitors
    
    def _format_display_name(self, monitor: Dict[str, Any]) -> str:
        """Format display name for monitor with folder context.
        
        Args:
            monitor: Monitor dictionary
            
        Returns:
            Formatted display name
        """
        name = monitor.get("name", "Unnamed")
        content_type = monitor.get("contentType", "")
        folder_path = monitor.get("folder_path", "")
        
        if content_type == "MonitorsLibraryFolder":
            return f"📁 {name}"
        elif content_type == "MonitorsLibraryMonitor":
            if folder_path and folder_path != "/" and not folder_path.startswith("/unknown"):
                return f"📊 {name}"
            else:
                return f"📊 {name}"
        else:
            return name
    
    async def search_monitors(
        self,
        search_query: str,
        search_fields: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search monitors with advanced search capabilities and comprehensive error handling.
        
        Args:
            search_query: Search query string
            search_fields: Fields to search in (name, description, query)
            limit: Maximum number of results to return
            offset: Starting position for pagination
            
        Returns:
            Dictionary containing search results with relevance scoring
            
        Raises:
            MonitorValidationError: If search parameters are invalid
            MonitorError: If search operation fails
            RateLimitError: If rate limit is exceeded
        """
        async def _search_monitors_impl():
            # Validate search query
            if not search_query or not search_query.strip():
                raise MonitorValidationError(
                    "Search query cannot be empty",
                    field_name="search_query",
                    field_value=search_query,
                    context=create_monitor_error_context("search_monitors")
                )
            
            # Validate pagination parameters
            validated_limit, validated_offset = await validate_pagination_params(
                limit, offset, "search_monitors"
            )
            
            # Validate search fields
            if search_fields is not None:
                valid_fields = ["name", "description", "query"]
                invalid_fields = [field for field in search_fields if field not in valid_fields]
                if invalid_fields:
                    raise MonitorValidationError(
                        f"Invalid search fields: {', '.join(invalid_fields)}. Valid fields: {', '.join(valid_fields)}",
                        field_name="search_fields",
                        field_value=search_fields,
                        context=create_monitor_error_context(
                            "search_monitors",
                            valid_fields=valid_fields,
                            invalid_fields=invalid_fields
                        )
                    )
            
            # Default search fields if not specified
            if search_fields is None:
                search_fields = ["name", "description", "query"]
            
            # Get all monitors first with error handling
            try:
                all_monitors_response = await self.list_monitors(limit=1000, offset=0)
                all_monitors = all_monitors_response.get("monitors", [])
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while searching monitors: {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "search_monitors",
                        search_query=search_query.strip()
                    )
                ) from e
            except Exception as e:
                raise MonitorError(
                    f"Failed to retrieve monitors for search: {str(e)}",
                    operation="search_monitors",
                    context=create_monitor_error_context(
                        "search_monitors",
                        search_query=search_query.strip(),
                        retrieval_error=str(e)
                    )
                ) from e
            
            # Perform client-side search with relevance scoring
            try:
                search_results = self._perform_search_with_scoring(
                    all_monitors, search_query.strip(), search_fields
                )
            except Exception as e:
                raise MonitorError(
                    f"Search scoring failed: {str(e)}",
                    operation="search_monitors",
                    context=create_monitor_error_context(
                        "search_monitors",
                        search_query=search_query.strip(),
                        scoring_error=str(e),
                        monitor_count=len(all_monitors)
                    )
                ) from e
            
            # Apply pagination to search results
            total_results = len(search_results)
            paginated_results = search_results[validated_offset:validated_offset + validated_limit]
            
            response = {
                "success": True,
                "monitors": paginated_results,
                "search_metadata": {
                    "query": search_query.strip(),
                    "fields_searched": search_fields,
                    "total_matches": total_results,
                    "returned_count": len(paginated_results),
                    "offset": validated_offset,
                    "limit": validated_limit,
                    "has_more": (validated_offset + len(paginated_results)) < total_results
                }
            }
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "search_monitors",
            _search_monitors_impl,
            timeout_override=30.0  # Search operations may take longer
        )
    
    def _perform_search_with_scoring(
        self,
        monitors: List[Dict[str, Any]],
        search_query: str,
        search_fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Perform search with relevance scoring.
        
        Args:
            monitors: List of monitor dictionaries
            search_query: Search query string
            search_fields: Fields to search in
            
        Returns:
            List of monitors with relevance scores, sorted by relevance
        """
        import re
        
        search_terms = search_query.lower().split()
        scored_monitors = []
        
        for monitor in monitors:
            score = 0
            matches = {}
            
            for field in search_fields:
                field_value = str(monitor.get(field, "")).lower()
                field_matches = []
                
                for term in search_terms:
                    # Exact match gets highest score
                    if term in field_value:
                        if field == "name":
                            score += 10  # Name matches are most important
                        elif field == "description":
                            score += 5
                        elif field == "query":
                            score += 3
                        
                        field_matches.append(term)
                        
                        # Bonus for exact word match
                        if re.search(r'\b' + re.escape(term) + r'\b', field_value):
                            score += 2
                
                if field_matches:
                    matches[field] = field_matches
            
            # Only include monitors that have at least one match
            if score > 0:
                monitor_with_score = monitor.copy()
                monitor_with_score["_search_score"] = score
                monitor_with_score["_search_matches"] = matches
                scored_monitors.append(monitor_with_score)
        
        # Sort by relevance score (highest first)
        scored_monitors.sort(key=lambda x: x["_search_score"], reverse=True)
        
        return scored_monitors
    
    async def get_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Get detailed monitor configuration and metadata.
        
        Args:
            monitor_id: Unique identifier for the monitor
            
        Returns:
            Dictionary containing detailed monitor information with formatted configuration
            
        Raises:
            MonitorValidationError: If monitor_id is invalid
            MonitorNotFoundError: If monitor is not found
            MonitorPermissionError: If insufficient permissions
            MonitorError: If monitor operation fails
        """
        async def _get_monitor_impl():
            # Validate monitor_id with enhanced validation
            validated_monitor_id = await validate_monitor_id(monitor_id, "get_monitor")
            
            # Get monitor from API with error handling
            try:
                monitor_data = await self.api_client.get_monitor(validated_monitor_id)
            except APIError as e:
                # The error handler will convert this to appropriate monitor error
                raise e
            
            # Format the response with enhanced information
            try:
                formatted_response = self._format_monitor_details(monitor_data)
            except Exception as e:
                raise MonitorError(
                    f"Failed to format monitor details: {str(e)}",
                    monitor_id=validated_monitor_id,
                    monitor_name=monitor_data.get("name"),
                    operation="get_monitor",
                    context=create_monitor_error_context(
                        "get_monitor",
                        monitor_id=validated_monitor_id,
                        format_error=str(e)
                    )
                ) from e
            
            return formatted_response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "get_monitor",
            _get_monitor_impl,
            monitor_id=monitor_id
        )
    
    def _format_monitor_details(self, monitor_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format monitor data with enhanced details and readable configuration.
        
        Args:
            monitor_data: Raw monitor data from API
            
        Returns:
            Dictionary with formatted monitor details
        """
        # Extract basic information
        monitor_id = monitor_data.get("id")
        name = monitor_data.get("name")
        description = monitor_data.get("description", "")
        monitor_type = monitor_data.get("monitorType")
        query = monitor_data.get("query", "")
        is_disabled = monitor_data.get("isDisabled", False)
        
        # Format timestamps
        created_at = monitor_data.get("createdAt")
        modified_at = monitor_data.get("modifiedAt")
        created_by = monitor_data.get("createdBy")
        modified_by = monitor_data.get("modifiedBy")
        version = monitor_data.get("version", 1)
        
        # Parse and format trigger conditions
        trigger_conditions = monitor_data.get("triggers", [])
        formatted_triggers = self._format_trigger_conditions(trigger_conditions)
        
        # Parse and format notifications
        notifications = monitor_data.get("notifications", [])
        formatted_notifications = self._format_notification_configurations(notifications)
        
        # Extract schedule and evaluation information
        evaluation_delay = monitor_data.get("evaluationDelay", "0m")
        group_notifications = monitor_data.get("groupNotifications", True)
        
        # Format query with syntax highlighting hints
        formatted_query = self._format_monitor_query(query, monitor_type)
        
        # Calculate configuration summary and statistics
        config_summary = self._generate_configuration_summary(
            monitor_data, formatted_triggers, formatted_notifications
        )
        
        # Build the formatted response
        response = {
            "success": True,
            "monitor": {
                "id": monitor_id,
                "name": name,
                "description": description,
                "type": self._convert_monitor_type_to_friendly(monitor_type),
                "api_type": monitor_type,
                "status": "disabled" if is_disabled else "enabled",
                "query": formatted_query,
                "trigger_conditions": formatted_triggers,
                "notifications": formatted_notifications,
                "schedule": {
                    "evaluation_delay": evaluation_delay,
                    "group_notifications": group_notifications
                },
                "metadata": {
                    "created_at": created_at,
                    "created_by": created_by,
                    "modified_at": modified_at,
                    "modified_by": modified_by,
                    "version": version
                },
                "configuration_summary": config_summary
            }
        }
        
        return response
    
    def sort_monitors(
        self,
        monitors: List[Dict[str, Any]],
        sort_by: str = "name",
        sort_order: str = "asc"
    ) -> List[Dict[str, Any]]:
        """Sort monitors by specified field and order.
        
        Args:
            monitors: List of monitor dictionaries
            sort_by: Field to sort by (name, created_at, modified_at, type, status)
            sort_order: Sort order (asc, desc)
            
        Returns:
            Sorted list of monitors
        """
        valid_sort_fields = ["name", "created_at", "modified_at", "type", "status"]
        if sort_by not in valid_sort_fields:
            logger.warning(f"Invalid sort field '{sort_by}', using 'name'")
            sort_by = "name"
        
        if sort_order not in ["asc", "desc"]:
            logger.warning(f"Invalid sort order '{sort_order}', using 'asc'")
            sort_order = "asc"
        
        # Map sort fields to actual monitor fields
        field_mapping = {
            "name": "name",
            "created_at": "createdAt",
            "modified_at": "modifiedAt",
            "type": "monitorType",
            "status": "isDisabled"  # We'll handle this specially
        }
        
        actual_field = field_mapping.get(sort_by, sort_by)
        reverse_order = (sort_order == "desc")
        
        try:
            if sort_by == "status":
                # Special handling for status (enabled/disabled)
                sorted_monitors = sorted(
                    monitors,
                    key=lambda x: (x.get("isDisabled", False), x.get("name", "")),
                    reverse=reverse_order
                )
            else:
                sorted_monitors = sorted(
                    monitors,
                    key=lambda x: x.get(actual_field, ""),
                    reverse=reverse_order
                )
            
            logger.debug(
                f"Sorted {len(monitors)} monitors by {sort_by} ({sort_order})"
            )
            
            return sorted_monitors
            
        except Exception as e:
            logger.warning(
                f"Failed to sort monitors by {sort_by}: {e}, returning original order"
            )
            return monitors
    
    def _calculate_monitor_statistics(self, monitors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate statistics for the monitor list.
        
        Args:
            monitors: List of monitor dictionaries
            
        Returns:
            Dictionary containing monitor statistics
        """
        if not monitors:
            return {
                "total_monitors": 0,
                "enabled_monitors": 0,
                "disabled_monitors": 0,
                "monitors_by_type": {},
                "monitors_by_creator": {}
            }
        
        enabled_count = 0
        disabled_count = 0
        type_counts = {}
        creator_counts = {}
        
        for monitor in monitors:
            # Count enabled/disabled
            if monitor.get("isDisabled", False):
                disabled_count += 1
            else:
                enabled_count += 1
            
            # Count by type
            monitor_type = monitor.get("monitorType", "Unknown")
            # Convert API type to user-friendly format
            if monitor_type == "MonitorsLibraryMonitor":
                monitor_type = "logs"
            elif monitor_type == "MetricsMonitor":
                monitor_type = "metrics"
            elif monitor_type == "SliMonitor":
                monitor_type = "SLI"
            
            type_counts[monitor_type] = type_counts.get(monitor_type, 0) + 1
            
            # Count by creator
            creator = monitor.get("createdBy", "Unknown")
            creator_counts[creator] = creator_counts.get(creator, 0) + 1
        
        return {
            "total_monitors": len(monitors),
            "enabled_monitors": enabled_count,
            "disabled_monitors": disabled_count,
            "monitors_by_type": type_counts,
            "monitors_by_creator": creator_counts
        }
    
    def _format_trigger_conditions(self, triggers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse and format trigger conditions into readable format.
        
        Args:
            triggers: List of trigger condition dictionaries from API
            
        Returns:
            Dictionary with formatted trigger conditions by severity level
        """
        formatted_triggers = {}
        
        for trigger in triggers:
            trigger_type = trigger.get("triggerType", "Unknown")
            
            # Extract trigger condition details
            threshold = trigger.get("threshold")
            threshold_type = trigger.get("thresholdType", "GreaterThan")
            time_range = trigger.get("timeRange", "-5m")
            occurrence_type = trigger.get("occurrenceType", "ResultCount")
            trigger_source = trigger.get("triggerSource", "AllResults")
            
            # Format threshold comparison for readability
            threshold_description = self._format_threshold_description(
                threshold, threshold_type, occurrence_type
            )
            
            # Format time range for readability
            time_description = self._format_time_range_description(time_range)
            
            # Format trigger source description
            source_description = self._format_trigger_source_description(trigger_source)
            
            formatted_triggers[trigger_type] = {
                "threshold": threshold,
                "threshold_type": threshold_type,
                "threshold_description": threshold_description,
                "time_range": time_range,
                "time_description": time_description,
                "occurrence_type": occurrence_type,
                "trigger_source": trigger_source,
                "source_description": source_description,
                "summary": f"Trigger when {threshold_description} {time_description} ({source_description})"
            }
        
        return formatted_triggers
    
    def _format_notification_configurations(self, notifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format notification configurations with destination details.
        
        Args:
            notifications: List of notification dictionaries from API
            
        Returns:
            List of formatted notification configurations
        """
        formatted_notifications = []
        
        for notification in notifications:
            action_type = notification.get("actionType", "Unknown")
            
            # Extract common notification fields
            subject = notification.get("subject", "")
            message_body = notification.get("messageBody", "")
            
            # Format based on notification type
            formatted_notification = {
                "type": action_type,
                "friendly_type": self._convert_notification_type_to_friendly(action_type),
                "subject": subject,
                "message_body": message_body,
                "destinations": []
            }
            
            # Extract type-specific destination information
            if action_type == "EmailAction":
                recipients = notification.get("emailRecipients", [])
                formatted_notification["destinations"] = [
                    {"type": "email", "address": recipient}
                    for recipient in recipients
                ]
            elif action_type == "WebhookAction":
                webhook_url = notification.get("webhookUrl", "")
                if webhook_url:
                    formatted_notification["destinations"] = [
                        {"type": "webhook", "url": webhook_url}
                    ]
            elif action_type == "SlackAction":
                channel = notification.get("slackChannel", "")
                if channel:
                    formatted_notification["destinations"] = [
                        {"type": "slack", "channel": channel}
                    ]
            elif action_type == "PagerDutyAction":
                integration_key = notification.get("integrationKey", "")
                if integration_key:
                    formatted_notification["destinations"] = [
                        {"type": "pagerduty", "integration_key": integration_key[:8] + "..."}
                    ]
            
            # Add summary description
            dest_count = len(formatted_notification["destinations"])
            dest_summary = f"{dest_count} destination{'s' if dest_count != 1 else ''}"
            formatted_notification["summary"] = f"{formatted_notification['friendly_type']} to {dest_summary}"
            
            formatted_notifications.append(formatted_notification)
        
        return formatted_notifications
    
    def _format_monitor_query(self, query: str, monitor_type: str) -> Dict[str, Any]:
        """Extract and format monitor query with syntax highlighting hints.
        
        Args:
            query: Raw query string
            monitor_type: Type of monitor (affects query syntax)
            
        Returns:
            Dictionary with formatted query information
        """
        # Determine query language based on monitor type
        query_language = "sumoql"  # Default
        if monitor_type == "MetricsMonitor":
            query_language = "metrics"
        elif monitor_type == "SliMonitor":
            query_language = "sli"
        
        # Extract key components from query
        query_components = self._extract_query_components(query, query_language)
        
        return {
            "raw": query,
            "language": query_language,
            "formatted": query.strip(),
            "components": query_components,
            "length": len(query),
            "line_count": len(query.split('\n')),
            "syntax_hints": self._generate_syntax_hints(query, query_language)
        }
    
    def _generate_configuration_summary(
        self,
        monitor_data: Dict[str, Any],
        formatted_triggers: Dict[str, Any],
        formatted_notifications: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate monitor configuration summary and statistics.
        
        Args:
            monitor_data: Raw monitor data
            formatted_triggers: Formatted trigger conditions
            formatted_notifications: Formatted notifications
            
        Returns:
            Dictionary with configuration summary
        """
        # Count trigger conditions by severity
        trigger_count = len(formatted_triggers)
        has_critical = "Critical" in formatted_triggers
        has_warning = "Warning" in formatted_triggers
        has_missing_data = "MissingData" in formatted_triggers
        
        # Count notifications by type
        notification_count = len(formatted_notifications)
        notification_types = {}
        for notification in formatted_notifications:
            notif_type = notification.get("friendly_type", "Unknown")
            notification_types[notif_type] = notification_types.get(notif_type, 0) + 1
        
        # Calculate complexity score (simple heuristic)
        complexity_score = 0
        complexity_score += trigger_count * 2  # Each trigger adds complexity
        complexity_score += notification_count  # Each notification adds complexity
        query_length = len(monitor_data.get("query", ""))
        if query_length > 500:
            complexity_score += 2
        elif query_length > 200:
            complexity_score += 1
        
        complexity_level = "Simple"
        if complexity_score > 8:
            complexity_level = "Complex"
        elif complexity_score > 4:
            complexity_level = "Moderate"
        
        return {
            "trigger_summary": {
                "total_conditions": trigger_count,
                "has_critical": has_critical,
                "has_warning": has_warning,
                "has_missing_data": has_missing_data,
                "severity_levels": list(formatted_triggers.keys())
            },
            "notification_summary": {
                "total_notifications": notification_count,
                "notification_types": notification_types,
                "total_destinations": sum(
                    len(notif.get("destinations", []))
                    for notif in formatted_notifications
                )
            },
            "complexity": {
                "score": complexity_score,
                "level": complexity_level,
                "factors": {
                    "trigger_conditions": trigger_count,
                    "notifications": notification_count,
                    "query_length": query_length
                }
            },
            "configuration_health": self._assess_configuration_health(
                formatted_triggers, formatted_notifications, monitor_data
            )
        }
    
    def _format_threshold_description(self, threshold: float, threshold_type: str, occurrence_type: str) -> str:
        """Format threshold comparison for human readability.
        
        Args:
            threshold: Threshold value
            threshold_type: Type of comparison (GreaterThan, LessThan, etc.)
            occurrence_type: Type of occurrence (ResultCount, AtLeastOnce, etc.)
            
        Returns:
            Human-readable threshold description
        """
        # Map threshold types to readable operators
        operator_map = {
            "GreaterThan": ">",
            "LessThan": "<",
            "GreaterThanOrEqual": ">=",
            "LessThanOrEqual": "<="
        }
        
        operator = operator_map.get(threshold_type, threshold_type)
        
        # Format based on occurrence type
        if occurrence_type == "ResultCount":
            return f"result count {operator} {threshold}"
        elif occurrence_type == "AtLeastOnce":
            return f"value {operator} {threshold} at least once"
        elif occurrence_type == "Always":
            return f"value {operator} {threshold} always"
        else:
            return f"value {operator} {threshold}"
    
    def _format_time_range_description(self, time_range: str) -> str:
        """Format time range for human readability.
        
        Args:
            time_range: Time range string (e.g., "-5m", "-1h")
            
        Returns:
            Human-readable time description
        """
        # Parse time range
        if time_range.startswith("-"):
            time_value = time_range[1:]
        else:
            time_value = time_range
        
        # Convert to readable format
        if time_value.endswith("s"):
            unit = "second"
            value = time_value[:-1]
        elif time_value.endswith("m"):
            unit = "minute"
            value = time_value[:-1]
        elif time_value.endswith("h"):
            unit = "hour"
            value = time_value[:-1]
        elif time_value.endswith("d"):
            unit = "day"
            value = time_value[:-1]
        else:
            return f"over {time_range}"
        
        # Add plural if needed
        try:
            num_value = int(value)
            if num_value != 1:
                unit += "s"
            return f"over the last {num_value} {unit}"
        except ValueError:
            return f"over {time_range}"
    
    def _format_trigger_source_description(self, trigger_source: str) -> str:
        """Format trigger source for human readability.
        
        Args:
            trigger_source: Trigger source type
            
        Returns:
            Human-readable source description
        """
        source_map = {
            "AllResults": "all results",
            "AnyTimeSeries": "any time series",
            "AllTimeSeries": "all time series"
        }
        
        return source_map.get(trigger_source, trigger_source.lower())
    
    def _convert_monitor_type_to_friendly(self, monitor_type: str) -> str:
        """Convert API monitor type to user-friendly format.
        
        Args:
            monitor_type: API monitor type
            
        Returns:
            User-friendly monitor type
        """
        type_map = {
            "MonitorsLibraryMonitor": "logs",
            "MetricsMonitor": "metrics",
            "SliMonitor": "SLI"
        }
        
        return type_map.get(monitor_type, monitor_type)
    
    def _convert_notification_type_to_friendly(self, action_type: str) -> str:
        """Convert API notification type to user-friendly format.
        
        Args:
            action_type: API notification action type
            
        Returns:
            User-friendly notification type
        """
        type_map = {
            "EmailAction": "Email",
            "WebhookAction": "Webhook",
            "SlackAction": "Slack",
            "PagerDutyAction": "PagerDuty"
        }
        
        return type_map.get(action_type, action_type)
    
    def _extract_query_components(self, query: str, query_language: str) -> Dict[str, Any]:
        """Extract key components from monitor query.
        
        Args:
            query: Query string
            query_language: Query language type
            
        Returns:
            Dictionary with extracted query components
        """
        components = {
            "keywords": [],
            "operators": [],
            "fields": [],
            "functions": []
        }
        
        # Basic keyword extraction (this could be enhanced with proper parsing)
        import re
        
        # Common SumoQL keywords
        if query_language == "sumoql":
            keywords = re.findall(r'\b(where|and|or|by|count|sum|avg|max|min|parse|json|csv|timeslice)\b', query, re.IGNORECASE)
            components["keywords"] = list(set(keywords))
            
            # Extract field references (simple heuristic)
            fields = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\s*=', query)
            components["fields"] = [field.replace('=', '').strip() for field in fields]
        
        return components
    
    def _generate_syntax_hints(self, query: str, query_language: str) -> List[str]:
        """Generate syntax highlighting hints for the query.
        
        Args:
            query: Query string
            query_language: Query language type
            
        Returns:
            List of syntax highlighting hints
        """
        hints = []
        
        # Add language-specific hints
        if query_language == "sumoql":
            hints.append("SumoQL query - supports where, parse, timeslice operators")
        elif query_language == "metrics":
            hints.append("Metrics query - supports metric(), quantize(), and aggregation functions")
        elif query_language == "sli":
            hints.append("SLI query - supports success/total ratio calculations")
        
        # Add complexity hints
        line_count = len(query.split('\n'))
        if line_count > 10:
            hints.append("Multi-line query - consider breaking into smaller components")
        
        if len(query) > 1000:
            hints.append("Long query - consider optimization for better performance")
        
        return hints
    
    def _assess_configuration_health(
        self,
        formatted_triggers: Dict[str, Any],
        formatted_notifications: List[Dict[str, Any]],
        monitor_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Assess the health and completeness of monitor configuration.
        
        Args:
            formatted_triggers: Formatted trigger conditions
            formatted_notifications: Formatted notifications
            monitor_data: Raw monitor data
            
        Returns:
            Dictionary with configuration health assessment
        """
        issues = []
        warnings = []
        recommendations = []
        
        # Check for missing critical trigger
        if "Critical" not in formatted_triggers:
            warnings.append("No Critical trigger condition defined")
            recommendations.append("Consider adding a Critical trigger for high-severity alerts")
        
        # Check for notifications
        if not formatted_notifications:
            issues.append("No notification actions configured")
            recommendations.append("Add at least one notification action to receive alerts")
        
        # Check for missing description
        description = monitor_data.get("description", "")
        if not description or len(description.strip()) < 10:
            warnings.append("Monitor description is missing or too short")
            recommendations.append("Add a detailed description explaining the monitor's purpose")
        
        # Check evaluation delay
        evaluation_delay = monitor_data.get("evaluationDelay", "0m")
        if evaluation_delay == "0m":
            recommendations.append("Consider adding evaluation delay to reduce false positives")
        
        # Determine overall health score
        health_score = 100
        health_score -= len(issues) * 20  # Issues are more serious
        health_score -= len(warnings) * 10  # Warnings are less serious
        health_score = max(0, health_score)  # Don't go below 0
        
        # Determine health level
        if health_score >= 90:
            health_level = "Excellent"
        elif health_score >= 70:
            health_level = "Good"
        elif health_score >= 50:
            health_level = "Fair"
        else:
            health_level = "Poor"
        
        return {
            "score": health_score,
            "level": health_level,
            "issues": issues,
            "warnings": warnings,
            "recommendations": recommendations,
            "summary": f"Configuration health: {health_level} ({health_score}/100)"
        }
    
    async def create_monitor(
        self,
        name: str,
        query: str,
        trigger_conditions: Dict[str, Any],
        description: str = "",
        type: str = "MonitorsLibraryMonitor",
        notifications: Optional[List[Dict[str, Any]]] = None,
        is_disabled: bool = False,
        evaluation_delay: str = "0m",
        **kwargs
    ) -> Dict[str, Any]:
        """Create new monitor with comprehensive validation and error handling.
        
        Args:
            name: Monitor name (required, max 255 characters)
            query: Monitor query string (required)
            trigger_conditions: Trigger conditions for different severity levels
            description: Monitor description (optional)
            type: Monitor type (MonitorsLibraryMonitor, MetricsMonitor, SliMonitor)
            notifications: List of notification actions (optional)
            is_disabled: Whether monitor should be created in disabled state
            evaluation_delay: Delay before evaluation (e.g., '5m')
            **kwargs: Additional monitor configuration parameters
            
        Returns:
            Dictionary containing created monitor information and validation results
            
        Raises:
            MonitorValidationError: If monitor configuration is invalid
            MonitorConfigurationError: If monitor configuration has issues
            MonitorPermissionError: If insufficient permissions
            MonitorError: If monitor creation fails
        """
        async def _create_monitor_impl():
            # Initialize notifications if not provided
            if notifications is None:
                notifications_list = []
            else:
                notifications_list = notifications
            
            # Step 1: Validate basic parameters
            if not name or not name.strip():
                raise MonitorValidationError(
                    "Monitor name is required and cannot be empty",
                    field_name="name",
                    field_value=name,
                    context=create_monitor_error_context("create_monitor")
                )
            
            if len(name.strip()) > 255:
                raise MonitorValidationError(
                    "Monitor name cannot exceed 255 characters",
                    field_name="name",
                    field_value=name,
                    context=create_monitor_error_context("create_monitor", name_length=len(name))
                )
            
            if not query or not query.strip():
                raise MonitorValidationError(
                    "Monitor query is required and cannot be empty",
                    field_name="query",
                    field_value=query,
                    context=create_monitor_error_context("create_monitor", monitor_name=name.strip())
                )
            
            if not trigger_conditions:
                raise MonitorValidationError(
                    "Trigger conditions are required",
                    field_name="trigger_conditions",
                    field_value=trigger_conditions,
                    context=create_monitor_error_context("create_monitor", monitor_name=name.strip())
                )
            
            # Step 2: Validate monitor configuration using Pydantic models
            monitor_config_data = {
                "name": name.strip(),
                "description": description,
                "type": type,
                "query": query.strip(),
                "trigger_conditions": trigger_conditions,
                "notifications": notifications_list,
                "is_disabled": is_disabled,
                "evaluation_delay": evaluation_delay
            }
            
            # Add any additional configuration from kwargs
            for key, value in kwargs.items():
                if key not in monitor_config_data:
                    monitor_config_data[key] = value
            
            # Validate using Pydantic model with enhanced error handling
            try:
                from ..models.monitor import MonitorConfig
                validated_config = MonitorConfig(**monitor_config_data)
            except Exception as e:
                raise MonitorConfigurationError(
                    f"Monitor configuration validation failed: {str(e)}",
                    monitor_name=name.strip(),
                    config_section="basic_validation",
                    config_errors=[str(e)],
                    context=create_monitor_error_context(
                        "create_monitor",
                        monitor_name=name.strip(),
                        validation_error=str(e)
                    )
                ) from e
            
            # Step 3: Perform comprehensive validation checks
            try:
                validation_results = await self._perform_comprehensive_validation(
                    validated_config, query.strip(), trigger_conditions, notifications_list
                )
            except Exception as e:
                raise MonitorConfigurationError(
                    f"Comprehensive validation failed: {str(e)}",
                    monitor_name=name.strip(),
                    config_section="comprehensive_validation",
                    config_errors=[str(e)],
                    context=create_monitor_error_context(
                        "create_monitor",
                        monitor_name=name.strip(),
                        validation_stage="comprehensive"
                    )
                ) from e
            
            if not validation_results["valid"]:
                # Collect all validation errors
                error_messages = validation_results["errors"]
                raise MonitorConfigurationError(
                    f"Monitor configuration validation failed: {'; '.join(error_messages)}",
                    monitor_name=name.strip(),
                    config_section="validation_rules",
                    config_errors=error_messages,
                    context=create_monitor_error_context(
                        "create_monitor",
                        monitor_name=name.strip(),
                        validation_details=validation_results
                    )
                )
            
            # Step 4: Create the monitor using API client with rate limiting
            try:
                created_monitor = await self.api_client.create_monitor(validated_config.dict())
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while creating monitor '{name.strip()}': {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "create_monitor",
                        monitor_name=name.strip(),
                        rate_limit_info={"retry_after": e.retry_after, "limit_type": e.limit_type}
                    )
                ) from e
            
            # Step 5: Format and enhance the response
            try:
                formatted_response = self._format_monitor_creation_response(
                    created_monitor, validation_results
                )
            except Exception as e:
                # Monitor was created but formatting failed - log warning and return basic response
                logger.warning(
                    "Monitor created successfully but response formatting failed",
                    extra={
                        "monitor_id": created_monitor.get("id"),
                        "monitor_name": created_monitor.get("name"),
                        "format_error": str(e)
                    }
                )
                formatted_response = {
                    "success": True,
                    "monitor": created_monitor,
                    "validation_results": validation_results,
                    "formatting_warning": f"Response formatting failed: {str(e)}"
                }
            
            return formatted_response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "create_monitor",
            _create_monitor_impl,
            monitor_name=name,
            timeout_override=45.0  # Monitor creation may take longer
        )
    
    async def _execute_monitor_operation_with_error_handling(
        self,
        operation: str,
        func: Callable,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        timeout_override: Optional[float] = None,
        **kwargs
    ) -> Any:
        """Execute monitor operation with comprehensive error handling and logging.
        
        This is a helper method that wraps monitor operations with consistent
        error handling, logging, and resilience patterns.
        
        Args:
            operation: Name of the monitor operation
            func: Function to execute
            monitor_id: Optional monitor ID for context
            monitor_name: Optional monitor name for context
            timeout_override: Optional timeout override
            **kwargs: Additional arguments for the function
            
        Returns:
            Function result with enhanced error context
            
        Raises:
            MonitorError: Enhanced monitor-specific error
        """
        return await self.error_handler.execute_with_error_handling(
            operation,
            func,
            monitor_id=monitor_id,
            monitor_name=monitor_name,
            timeout_override=timeout_override,
            **kwargs
        )
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get comprehensive error statistics for monitoring and debugging.
        
        Returns:
            Dictionary containing error statistics, circuit breaker status,
            and operational health metrics
        """
        return {
            "monitor_tools_errors": self.error_handler.get_error_statistics(),
            "resilience_status": self.error_handler.resilient_client.get_health_status(),
            "timeout_configuration": {
                "list_monitors": self.error_handler.timeout_manager.get_timeout("list_monitors"),
                "get_monitor": self.error_handler.timeout_manager.get_timeout("get_monitor"),
                "create_monitor": self.error_handler.timeout_manager.get_timeout("create_monitor"),
                "update_monitor": self.error_handler.timeout_manager.get_timeout("update_monitor"),
                "delete_monitor": self.error_handler.timeout_manager.get_timeout("delete_monitor")
            }
        }
    
    def reset_error_statistics(self):
        """Reset error statistics for monitoring tools.
        
        This method is useful for testing or periodic cleanup of error metrics.
        """
        self.error_handler.reset_error_statistics()
        logger.info("Reset monitor tools error statistics")    

    async def update_monitor(
        self,
        monitor_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        query: Optional[str] = None,
        trigger_conditions: Optional[Dict[str, Any]] = None,
        notifications: Optional[List[Dict[str, Any]]] = None,
        is_disabled: Optional[bool] = None,
        evaluation_delay: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Update existing monitor configuration with comprehensive error handling.
        
        Args:
            monitor_id: Unique identifier for the monitor to update
            name: New monitor name (max 255 characters)
            description: New monitor description
            query: New monitor query string
            trigger_conditions: New trigger conditions for different severity levels
            notifications: New notification actions
            is_disabled: Whether monitor should be disabled
            evaluation_delay: New evaluation delay (e.g., '5m')
            **kwargs: Additional monitor configuration parameters
            
        Returns:
            Dictionary containing updated monitor information and change confirmation
            
        Raises:
            MonitorValidationError: If monitor_id or update parameters are invalid
            MonitorNotFoundError: If monitor doesn't exist
            MonitorPermissionError: If insufficient permissions
            MonitorConfigurationError: If update configuration is invalid
            MonitorOperationError: If update conflicts exist
            MonitorError: If monitor update fails
        """
        async def _update_monitor_impl():
            # Validate monitor_id with enhanced validation
            validated_monitor_id = await validate_monitor_id(monitor_id, "update_monitor")
            
            # Validate update parameters
            update_fields = {
                "name": name, "description": description, "query": query,
                "trigger_conditions": trigger_conditions, "notifications": notifications,
                "is_disabled": is_disabled, "evaluation_delay": evaluation_delay
            }
            update_fields.update(kwargs)
            
            # Remove None values to get actual update fields
            actual_updates = {k: v for k, v in update_fields.items() if v is not None}
            
            if not actual_updates:
                raise MonitorValidationError(
                    "No update parameters provided",
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        available_fields=list(update_fields.keys())
                    )
                )
            
            # Validate name length if provided
            if name is not None and len(name.strip()) > 255:
                raise MonitorValidationError(
                    "Monitor name cannot exceed 255 characters",
                    field_name="name",
                    field_value=name,
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        name_length=len(name)
                    )
                )
            
            # Step 1: Get current monitor configuration for merging
            try:
                current_monitor = await self.get_monitor(validated_monitor_id)
                current_config = current_monitor.get("monitor", current_monitor)
            except MonitorNotFoundError:
                raise
            except Exception as e:
                raise MonitorError(
                    f"Failed to retrieve current monitor configuration: {str(e)}",
                    monitor_id=validated_monitor_id,
                    operation="update_monitor",
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        retrieval_error=str(e)
                    )
                ) from e
            
            # Step 2: Build update configuration with selective field modification
            try:
                update_config = await self._merge_monitor_configuration(
                    current_config, actual_updates
                )
            except Exception as e:
                raise MonitorConfigurationError(
                    f"Failed to merge monitor configuration: {str(e)}",
                    monitor_id=validated_monitor_id,
                    monitor_name=current_config.get("name"),
                    config_section="configuration_merge",
                    config_errors=[str(e)],
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        merge_error=str(e)
                    )
                ) from e
            
            # Step 3: Validate updated configuration fields
            try:
                validation_results = await self._validate_monitor_updates(
                    current_config, update_config, validated_monitor_id
                )
            except Exception as e:
                raise MonitorConfigurationError(
                    f"Monitor update validation failed: {str(e)}",
                    monitor_id=validated_monitor_id,
                    monitor_name=current_config.get("name"),
                    config_section="update_validation",
                    config_errors=[str(e)],
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        validation_error=str(e)
                    )
                ) from e
            
            if not validation_results["valid"]:
                error_messages = validation_results["errors"]
                raise MonitorConfigurationError(
                    f"Monitor update validation failed: {'; '.join(error_messages)}",
                    monitor_id=validated_monitor_id,
                    monitor_name=current_config.get("name"),
                    config_section="validation_rules",
                    config_errors=error_messages,
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        validation_details=validation_results
                    )
                )
            
            # Step 4: Handle monitor version conflicts and concurrent modifications
            try:
                version_check_result = await self._handle_version_conflicts(
                    current_config, update_config, validated_monitor_id
                )
            except Exception as e:
                raise MonitorOperationError(
                    f"Version conflict check failed: {str(e)}",
                    monitor_id=validated_monitor_id,
                    monitor_name=current_config.get("name"),
                    operation="update_monitor",
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        version_check_error=str(e)
                    )
                ) from e
            
            if not version_check_result["can_update"]:
                raise MonitorOperationError(
                    f"Monitor {validated_monitor_id} has been modified by another process",
                    monitor_id=validated_monitor_id,
                    monitor_name=current_config.get("name"),
                    operation="update_monitor",
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        conflict_type="version_mismatch",
                        current_version=version_check_result.get("current_version")
                    )
                )
            
            # Step 5: Apply the update via API client
            try:
                updated_monitor = await self.api_client.update_monitor(
                    validated_monitor_id, update_config
                )
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while updating monitor '{validated_monitor_id}': {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "update_monitor",
                        monitor_id=validated_monitor_id,
                        monitor_name=current_config.get("name")
                    )
                ) from e
            
            # Step 6: Format and enhance the response
            try:
                formatted_response = await self._format_monitor_update_response(
                    current_config, updated_monitor, actual_updates, validation_results
                )
            except Exception as e:
                # Monitor was updated but formatting failed - log warning and return basic response
                logger.warning(
                    "Monitor updated successfully but response formatting failed",
                    extra={
                        "monitor_id": validated_monitor_id,
                        "monitor_name": updated_monitor.get("name"),
                        "format_error": str(e)
                    }
                )
                formatted_response = {
                    "success": True,
                    "monitor": updated_monitor,
                    "changes_applied": actual_updates,
                    "validation_results": validation_results,
                    "formatting_warning": f"Response formatting failed: {str(e)}"
                }
            
            return formatted_response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "update_monitor",
            _update_monitor_impl,
            monitor_id=monitor_id,
            timeout_override=30.0
        )
        logger.info(
            "Updating monitor with partial updates and validation",
            extra={
                "monitor_id": monitor_id,
                "update_fields": [k for k, v in {
                    "name": name, "description": description, "query": query,
                    "trigger_conditions": trigger_conditions, "notifications": notifications,
                    "is_disabled": is_disabled, "evaluation_delay": evaluation_delay
                }.items() if v is not None] + list(kwargs.keys())
            }
        )
        
        # Validate monitor_id
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        try:
            # Step 1: Get current monitor configuration for merging
            logger.debug(f"Retrieving current monitor configuration for {monitor_id}")
            current_monitor = await self.get_monitor(monitor_id)
            
            if not current_monitor.get("success", True):
                raise APIError(
                    f"Failed to retrieve current monitor {monitor_id} for update",
                    context={"monitor_id": monitor_id, "operation": "update_monitor"}
                )
            
            current_config = current_monitor.get("monitor", current_monitor)
            
            # Step 2: Build update configuration with selective field modification
            update_config = await self._merge_monitor_configuration(
                current_config, {
                    "name": name,
                    "description": description,
                    "query": query,
                    "trigger_conditions": trigger_conditions,
                    "notifications": notifications,
                    "is_disabled": is_disabled,
                    "evaluation_delay": evaluation_delay,
                    **kwargs
                }
            )
            
            # Step 3: Validate updated configuration fields
            validation_results = await self._validate_monitor_updates(
                current_config, update_config, monitor_id
            )
            
            if not validation_results["valid"]:
                error_messages = validation_results["errors"]
                logger.error(
                    "Monitor update validation failed",
                    extra={
                        "monitor_id": monitor_id,
                        "errors": error_messages,
                        "warnings": validation_results.get("warnings", [])
                    }
                )
                raise ValidationError(
                    f"Monitor update validation failed: {'; '.join(error_messages)}",
                    validation_errors={
                        "configuration": error_messages,
                        "warnings": validation_results.get("warnings", [])
                    },
                    context={
                        "monitor_id": monitor_id,
                        "validation_details": validation_results
                    }
                )
            
            # Log any warnings
            if validation_results.get("warnings"):
                logger.warning(
                    "Monitor update has warnings",
                    extra={
                        "monitor_id": monitor_id,
                        "warnings": validation_results["warnings"]
                    }
                )
            
            # Step 4: Handle monitor version conflicts and concurrent modifications
            version_check_result = await self._handle_version_conflicts(
                current_config, update_config, monitor_id
            )
            
            if not version_check_result["can_update"]:
                raise APIError(
                    f"Monitor {monitor_id} has been modified by another process. Please refresh and try again.",
                    status_code=409,
                    context={
                        "monitor_id": monitor_id,
                        "conflict_type": "version_mismatch",
                        "current_version": version_check_result.get("current_version"),
                        "expected_version": version_check_result.get("expected_version")
                    }
                )
            
            # Step 5: Apply the update via API client
            logger.info(
                f"Applying monitor update via API for {monitor_id}",
                extra={
                    "monitor_id": monitor_id,
                    "changed_fields": validation_results.get("changed_fields", [])
                }
            )
            
            updated_monitor = await self.api_client.update_monitor(monitor_id, update_config)
            
            # Step 6: Return detailed change confirmation with applied modifications
            response = await self._format_monitor_update_response(
                current_config, updated_monitor, validation_results
            )
            
            logger.info(
                "Monitor updated successfully",
                extra={
                    "monitor_id": monitor_id,
                    "name": updated_monitor.get("name"),
                    "changed_fields": response.get("changes", {}).get("modified_fields", []),
                    "validation_warnings": len(validation_results.get("warnings", []))
                }
            )
            
            return response
            
        except ValidationError:
            # Re-raise validation errors as-is
            raise
            
        except APIError as e:
            # Handle API-specific errors with enhanced context
            logger.error(
                "Failed to update monitor via API",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "status_code": getattr(e, 'status_code', None)
                }
            )
            
            # Provide more specific error messages based on status code
            if hasattr(e, 'status_code'):
                if e.status_code == 404:
                    raise ValidationError(
                        f"Monitor {monitor_id} not found",
                        field_name="monitor_id",
                        field_value=monitor_id,
                        context={"suggestion": "Verify the monitor ID is correct"}
                    ) from e
                elif e.status_code == 403:
                    raise APIError(
                        f"Insufficient permissions to update monitor {monitor_id}: {e.message}",
                        status_code=403,
                        context={
                            "operation": "update_monitor",
                            "monitor_id": monitor_id,
                            "error_type": "permission_denied"
                        }
                    ) from e
                elif e.status_code == 409:
                    raise APIError(
                        f"Monitor {monitor_id} was modified by another process: {e.message}",
                        status_code=409,
                        context={
                            "monitor_id": monitor_id,
                            "error_type": "concurrent_modification",
                            "suggestion": "Refresh the monitor and try the update again"
                        }
                    ) from e
            
            # Re-raise with enhanced context
            raise APIError(
                f"Failed to update monitor {monitor_id}: {e.message}",
                status_code=getattr(e, 'status_code', None),
                request_id=getattr(e, 'request_id', None),
                context={
                    "operation": "update_monitor",
                    "monitor_id": monitor_id
                }
            ) from e
            
        except Exception as e:
            logger.error(
                "Unexpected error updating monitor",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise APIError(
                f"Unexpected error updating monitor {monitor_id}: {str(e)}",
                context={
                    "operation": "update_monitor",
                    "monitor_id": monitor_id,
                    "error_type": type(e).__name__
                }
            ) from e

    async def _merge_monitor_configuration(
        self,
        current_config: Dict[str, Any],
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Implement configuration merging for partial updates.
        
        Args:
            current_config: Current monitor configuration
            updates: Update parameters (may contain None values)
            
        Returns:
            Merged configuration with updates applied
        """
        # Start with current configuration
        merged_config = current_config.copy()
        
        # Apply non-None updates
        for key, value in updates.items():
            if value is not None:
                if key in ["trigger_conditions", "notifications"]:
                    # For complex objects, replace entirely if provided
                    merged_config[key] = value
                else:
                    # For simple fields, update directly
                    merged_config[key] = value
        
        logger.debug(
            "Merged monitor configuration",
            extra={
                "updated_fields": [k for k, v in updates.items() if v is not None],
                "total_fields": len(merged_config)
            }
        )
        
        return merged_config

    async def _validate_monitor_updates(
        self,
        current_config: Dict[str, Any],
        update_config: Dict[str, Any],
        monitor_id: str
    ) -> Dict[str, Any]:
        """Validate updated configuration fields before applying changes.
        
        Args:
            current_config: Current monitor configuration
            update_config: Updated configuration to validate
            monitor_id: Monitor ID for context
            
        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "changed_fields": []
        }
        
        try:
            # Identify changed fields
            changed_fields = []
            for key, new_value in update_config.items():
                current_value = current_config.get(key)
                if current_value != new_value:
                    changed_fields.append(key)
            
            validation_result["changed_fields"] = changed_fields
            
            if not changed_fields:
                validation_result["warnings"].append("No changes detected in update request")
                return validation_result
            
            # Validate updated trigger conditions and thresholds
            if "trigger_conditions" in changed_fields:
                trigger_validation = await self._validate_updated_trigger_conditions(
                    update_config.get("trigger_conditions", {}),
                    current_config.get("trigger_conditions", {})
                )
                validation_result["errors"].extend(trigger_validation.get("errors", []))
                validation_result["warnings"].extend(trigger_validation.get("warnings", []))
            
            # Handle notification configuration updates and validation
            if "notifications" in changed_fields:
                notification_validation = await self._validate_updated_notifications(
                    update_config.get("notifications", []),
                    current_config.get("notifications", [])
                )
                validation_result["errors"].extend(notification_validation.get("errors", []))
                validation_result["warnings"].extend(notification_validation.get("warnings", []))
            
            # Add schedule modification with validation
            if "evaluation_delay" in changed_fields:
                schedule_validation = await self._validate_schedule_modification(
                    update_config.get("evaluation_delay"),
                    current_config.get("evaluation_delay")
                )
                validation_result["errors"].extend(schedule_validation.get("errors", []))
                validation_result["warnings"].extend(schedule_validation.get("warnings", []))
            
            # Validate query changes if present
            if "query" in changed_fields:
                query_validation = await self._validate_query_syntax(
                    update_config.get("query", ""),
                    update_config.get("type", current_config.get("monitorType", "MonitorsLibraryMonitor"))
                )
                validation_result["errors"].extend(query_validation.get("errors", []))
                validation_result["warnings"].extend(query_validation.get("warnings", []))
            
            # Validate name changes
            if "name" in changed_fields:
                name_validation = self._validate_monitor_name_update(
                    update_config.get("name"),
                    current_config.get("name")
                )
                validation_result["errors"].extend(name_validation.get("errors", []))
                validation_result["warnings"].extend(name_validation.get("warnings", []))
            
            # Set overall validity
            validation_result["valid"] = len(validation_result["errors"]) == 0
            
            logger.debug(
                "Monitor update validation completed",
                extra={
                    "monitor_id": monitor_id,
                    "changed_fields": changed_fields,
                    "valid": validation_result["valid"],
                    "error_count": len(validation_result["errors"]),
                    "warning_count": len(validation_result["warnings"])
                }
            )
            
            return validation_result
            
        except Exception as e:
            logger.error(
                "Error during monitor update validation",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            validation_result["valid"] = False
            validation_result["errors"].append(f"Validation error: {str(e)}")
            return validation_result

    async def _validate_updated_trigger_conditions(
        self,
        new_conditions: Dict[str, Any],
        current_conditions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate updated trigger conditions and thresholds.
        
        Args:
            new_conditions: New trigger conditions
            current_conditions: Current trigger conditions
            
        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        try:
            # Validate each trigger condition
            for trigger_type, condition in new_conditions.items():
                if not isinstance(condition, dict):
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' must be a dictionary"
                    )
                    continue
                
                # Validate threshold
                threshold = condition.get("threshold")
                if threshold is None:
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' missing threshold"
                    )
                elif not isinstance(threshold, (int, float)):
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' threshold must be a number"
                    )
                
                # Validate threshold type
                threshold_type = condition.get("threshold_type")
                valid_threshold_types = ["GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual"]
                if threshold_type not in valid_threshold_types:
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' has invalid threshold_type. "
                        f"Must be one of: {', '.join(valid_threshold_types)}"
                    )
                
                # Validate time range
                time_range = condition.get("time_range")
                if not time_range:
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' missing time_range"
                    )
                elif not isinstance(time_range, str) or not time_range.strip():
                    validation_result["errors"].append(
                        f"Trigger condition '{trigger_type}' time_range must be a non-empty string"
                    )
                
                # Compare with current conditions for warnings
                current_condition = current_conditions.get(trigger_type, {})
                if current_condition:
                    current_threshold = current_condition.get("threshold")
                    if current_threshold and threshold and abs(threshold - current_threshold) > (current_threshold * 0.5):
                        validation_result["warnings"].append(
                            f"Trigger condition '{trigger_type}' threshold changed significantly "
                            f"from {current_threshold} to {threshold}"
                        )
            
            return validation_result
            
        except Exception as e:
            validation_result["errors"].append(f"Error validating trigger conditions: {str(e)}")
            return validation_result

    async def _validate_updated_notifications(
        self,
        new_notifications: List[Dict[str, Any]],
        current_notifications: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Handle notification configuration updates and validation.
        
        Args:
            new_notifications: New notification configurations
            current_notifications: Current notification configurations
            
        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        try:
            if not isinstance(new_notifications, list):
                validation_result["errors"].append("Notifications must be a list")
                return validation_result
            
            # Validate each notification
            for i, notification in enumerate(new_notifications):
                if not isinstance(notification, dict):
                    validation_result["errors"].append(f"Notification {i} must be a dictionary")
                    continue
                
                # Validate action type
                action_type = notification.get("action_type")
                valid_action_types = ["EmailAction", "WebhookAction", "SlackAction", "PagerDutyAction"]
                if action_type not in valid_action_types:
                    validation_result["errors"].append(
                        f"Notification {i} has invalid action_type. "
                        f"Must be one of: {', '.join(valid_action_types)}"
                    )
                
                # Validate based on action type
                if action_type == "EmailAction":
                    recipients = notification.get("recipients", [])
                    if not recipients:
                        validation_result["errors"].append(f"Email notification {i} missing recipients")
                    elif not isinstance(recipients, list):
                        validation_result["errors"].append(f"Email notification {i} recipients must be a list")
                    else:
                        # Validate email addresses
                        import re
                        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                        for email in recipients:
                            if not re.match(email_pattern, email):
                                validation_result["errors"].append(
                                    f"Email notification {i} has invalid email address: {email}"
                                )
                
                elif action_type == "WebhookAction":
                    webhook_url = notification.get("webhook_url")
                    if not webhook_url:
                        validation_result["errors"].append(f"Webhook notification {i} missing webhook_url")
                    elif not webhook_url.startswith(('http://', 'https://')):
                        validation_result["errors"].append(
                            f"Webhook notification {i} URL must start with http:// or https://"
                        )
            
            # Compare with current notifications for warnings
            if len(new_notifications) != len(current_notifications):
                validation_result["warnings"].append(
                    f"Number of notifications changed from {len(current_notifications)} to {len(new_notifications)}"
                )
            
            return validation_result
            
        except Exception as e:
            validation_result["errors"].append(f"Error validating notifications: {str(e)}")
            return validation_result

    async def _validate_schedule_modification(
        self,
        new_delay: Optional[str],
        current_delay: Optional[str]
    ) -> Dict[str, Any]:
        """Add schedule modification with validation.
        
        Args:
            new_delay: New evaluation delay
            current_delay: Current evaluation delay
            
        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        try:
            if new_delay is not None:
                # Validate delay format
                import re
                if not re.match(r'^\d+[smh]$', new_delay):
                    validation_result["errors"].append(
                        "Evaluation delay must be in format like '5m', '1h', '30s'"
                    )
                else:
                    # Parse delay value for warnings
                    delay_match = re.match(r'^(\d+)([smh])$', new_delay)
                    if delay_match:
                        value, unit = delay_match.groups()
                        value = int(value)
                        
                        # Convert to minutes for comparison
                        if unit == 's':
                            delay_minutes = value / 60
                        elif unit == 'm':
                            delay_minutes = value
                        elif unit == 'h':
                            delay_minutes = value * 60
                        
                        if delay_minutes > 60:  # More than 1 hour
                            validation_result["warnings"].append(
                                f"Evaluation delay of {new_delay} is quite long and may delay alert notifications"
                            )
                        elif delay_minutes < 1:  # Less than 1 minute
                            validation_result["warnings"].append(
                                f"Evaluation delay of {new_delay} is very short and may cause frequent evaluations"
                            )
            
            return validation_result
            
        except Exception as e:
            validation_result["errors"].append(f"Error validating schedule modification: {str(e)}")
            return validation_result

    def _validate_monitor_name_update(
        self,
        new_name: Optional[str],
        current_name: Optional[str]
    ) -> Dict[str, Any]:
        """Validate monitor name updates.
        
        Args:
            new_name: New monitor name
            current_name: Current monitor name
            
        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        try:
            if new_name is not None:
                # Validate name length and content
                if not new_name.strip():
                    validation_result["errors"].append("Monitor name cannot be empty")
                elif len(new_name) > 255:
                    validation_result["errors"].append("Monitor name cannot exceed 255 characters")
                else:
                    # Check for invalid characters
                    import re
                    if re.search(r'[<>:"/\\|?*]', new_name):
                        validation_result["errors"].append("Monitor name contains invalid characters")
                    
                    # Warning for significant name changes
                    if current_name and new_name.lower() != current_name.lower():
                        validation_result["warnings"].append(
                            f"Monitor name changing from '{current_name}' to '{new_name}'"
                        )
            
            return validation_result
            
        except Exception as e:
            validation_result["errors"].append(f"Error validating name update: {str(e)}")
            return validation_result

    async def _handle_version_conflicts(
        self,
        current_config: Dict[str, Any],
        update_config: Dict[str, Any],
        monitor_id: str
    ) -> Dict[str, Any]:
        """Handle monitor version conflicts and concurrent modifications.
        
        Args:
            current_config: Current monitor configuration
            update_config: Updated configuration
            monitor_id: Monitor ID
            
        Returns:
            Dictionary indicating if update can proceed
        """
        try:
            # Get fresh monitor data to check for concurrent modifications
            fresh_monitor = await self.api_client.get_monitor(monitor_id)
            
            current_version = current_config.get("version", 0)
            fresh_version = fresh_monitor.get("version", 0)
            
            if fresh_version > current_version:
                logger.warning(
                    f"Monitor {monitor_id} version conflict detected",
                    extra={
                        "current_version": current_version,
                        "fresh_version": fresh_version,
                        "monitor_id": monitor_id
                    }
                )
                return {
                    "can_update": False,
                    "current_version": current_version,
                    "expected_version": fresh_version,
                    "conflict_detected": True
                }
            
            return {
                "can_update": True,
                "current_version": current_version,
                "expected_version": fresh_version,
                "conflict_detected": False
            }
            
        except Exception as e:
            logger.warning(
                f"Could not check version conflicts for monitor {monitor_id}: {str(e)}",
                extra={"monitor_id": monitor_id, "error": str(e)}
            )
            # Allow update to proceed if version check fails
            return {
                "can_update": True,
                "version_check_failed": True,
                "error": str(e)
            }

    async def _format_monitor_update_response(
        self,
        original_config: Dict[str, Any],
        updated_monitor: Dict[str, Any],
        validation_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return detailed change confirmation with applied modifications.
        
        Args:
            original_config: Original monitor configuration
            updated_monitor: Updated monitor from API
            validation_results: Validation results
            
        Returns:
            Formatted response with change details
        """
        try:
            # Identify what actually changed
            changed_fields = validation_results.get("changed_fields", [])
            
            # Build change summary
            changes = {
                "modified_fields": changed_fields,
                "field_changes": {},
                "summary": f"Updated {len(changed_fields)} field(s)"
            }
            
            # Detail specific changes
            for field in changed_fields:
                original_value = original_config.get(field)
                new_value = updated_monitor.get(field)
                changes["field_changes"][field] = {
                    "from": original_value,
                    "to": new_value
                }
            
            # Format the response
            response = {
                "success": True,
                "message": f"Monitor '{updated_monitor.get('name')}' updated successfully",
                "monitor": updated_monitor,
                "changes": changes,
                "validation": {
                    "warnings": validation_results.get("warnings", []),
                    "warnings_count": len(validation_results.get("warnings", []))
                },
                "metadata": {
                    "monitor_id": updated_monitor.get("id"),
                    "name": updated_monitor.get("name"),
                    "type": updated_monitor.get("monitorType"),
                    "version": updated_monitor.get("version"),
                    "modified_at": updated_monitor.get("modifiedAt"),
                    "modified_by": updated_monitor.get("modifiedBy")
                }
            }
            
            # Add recommendations
            response["recommendations"] = self._generate_update_recommendations(
                changes, validation_results
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "Error formatting monitor update response",
                extra={"error": str(e), "error_type": type(e).__name__}
            )
            # Return basic response if formatting fails
            return {
                "success": True,
                "message": "Monitor updated successfully",
                "monitor": updated_monitor,
                "error": f"Response formatting error: {str(e)}"
            }

    def _generate_update_recommendations(
        self,
        changes: Dict[str, Any],
        validation_results: Dict[str, Any]
    ) -> List[str]:
        """Generate recommendations based on the update changes.
        
        Args:
            changes: Dictionary of changes made
            validation_results: Validation results
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        changed_fields = changes.get("modified_fields", [])
        
        # Recommendations based on changed fields
        if "trigger_conditions" in changed_fields:
            recommendations.append("Test the updated trigger conditions to ensure they work as expected")
        
        if "notifications" in changed_fields:
            recommendations.append("Verify notification destinations are working correctly")
        
        if "query" in changed_fields:
            recommendations.append("Monitor the updated query performance and result accuracy")
        
        if "is_disabled" in changed_fields:
            field_changes = changes.get("field_changes", {})
            disabled_change = field_changes.get("is_disabled", {})
            if disabled_change.get("to") is True:
                recommendations.append("Monitor is now disabled - enable when ready to resume monitoring")
            elif disabled_change.get("to") is False:
                recommendations.append("Monitor is now enabled and will start evaluating immediately")
        
        # Recommendations based on warnings
        warnings = validation_results.get("warnings", [])
        if warnings:
            recommendations.append(f"Review {len(warnings)} configuration warnings for optimization opportunities")
        
        # General recommendations
        if len(changed_fields) > 3:
            recommendations.append("Consider testing the monitor thoroughly due to multiple configuration changes")
        
        recommendations.append("Check monitor status and alert history to verify the update is working correctly")
        
        return recommendations

    async def _perform_comprehensive_validation(
        self,
        config: 'MonitorConfig',
        query: str,
        trigger_conditions: Dict[str, Any],
        notifications: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform comprehensive validation of monitor configuration.
        
        Args:
            config: Validated Pydantic monitor configuration
            query: Monitor query string
            trigger_conditions: Trigger conditions dictionary
            notifications: List of notification configurations
            
        Returns:
            Dictionary containing validation results with errors and warnings
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "query_syntax_valid": None,
            "trigger_conditions_valid": None,
            "notifications_valid": None
        }
        
        # Validate query syntax
        query_validation = await self._validate_query_syntax(query, config.type.value)
        validation_result["query_syntax_valid"] = query_validation["valid"]
        if not query_validation["valid"]:
            validation_result["errors"].extend(query_validation["errors"])
        validation_result["warnings"].extend(query_validation.get("warnings", []))
        
        # Validate trigger conditions
        trigger_validation = self._validate_trigger_conditions(trigger_conditions)
        validation_result["trigger_conditions_valid"] = trigger_validation["valid"]
        if not trigger_validation["valid"]:
            validation_result["errors"].extend(trigger_validation["errors"])
        validation_result["warnings"].extend(trigger_validation.get("warnings", []))
        
        # Validate notification configurations
        notification_validation = await self._validate_notification_configurations(notifications)
        validation_result["notifications_valid"] = notification_validation["valid"]
        if not notification_validation["valid"]:
            validation_result["errors"].extend(notification_validation["errors"])
        validation_result["warnings"].extend(notification_validation.get("warnings", []))
        
        # Perform cross-validation checks
        cross_validation = self._perform_cross_validation_checks(config, trigger_conditions, notifications)
        validation_result["warnings"].extend(cross_validation.get("warnings", []))
        if cross_validation.get("errors"):
            validation_result["errors"].extend(cross_validation["errors"])
        
        # Set overall validity
        validation_result["valid"] = len(validation_result["errors"]) == 0
        
        logger.debug(
            "Comprehensive validation completed",
            extra={
                "valid": validation_result["valid"],
                "error_count": len(validation_result["errors"]),
                "warning_count": len(validation_result["warnings"])
            }
        )
        
        return validation_result
    
    async def _validate_query_syntax(self, query: str, monitor_type: str) -> Dict[str, Any]:
        """Validate monitor query syntax and structure.
        
        Args:
            query: Monitor query string
            monitor_type: Type of monitor (affects query validation)
            
        Returns:
            Dictionary containing query validation results
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Basic query validation
        if not query or not query.strip():
            validation_result["errors"].append("Query cannot be empty")
            validation_result["valid"] = False
            return validation_result
        
        query = query.strip()
        
        # Check query length
        if len(query) > 10000:  # Reasonable limit for query length
            validation_result["errors"].append("Query is too long (maximum 10,000 characters)")
            validation_result["valid"] = False
        elif len(query) > 5000:
            validation_result["warnings"].append("Query is very long, consider simplifying for better performance")
        
        # Validate based on monitor type
        if monitor_type == "MonitorsLibraryMonitor":
            # SumoQL validation
            sumoql_validation = self._validate_sumoql_syntax(query)
            validation_result["errors"].extend(sumoql_validation.get("errors", []))
            validation_result["warnings"].extend(sumoql_validation.get("warnings", []))
            if sumoql_validation.get("errors"):
                validation_result["valid"] = False
                
        elif monitor_type == "MetricsMonitor":
            # Metrics query validation
            metrics_validation = self._validate_metrics_query_syntax(query)
            validation_result["errors"].extend(metrics_validation.get("errors", []))
            validation_result["warnings"].extend(metrics_validation.get("warnings", []))
            if metrics_validation.get("errors"):
                validation_result["valid"] = False
                
        elif monitor_type == "SliMonitor":
            # SLI query validation
            sli_validation = self._validate_sli_query_syntax(query)
            validation_result["errors"].extend(sli_validation.get("errors", []))
            validation_result["warnings"].extend(sli_validation.get("warnings", []))
            if sli_validation.get("errors"):
                validation_result["valid"] = False
        
        # Check for common query issues
        common_issues = self._check_common_query_issues(query)
        validation_result["warnings"].extend(common_issues)
        
        return validation_result
    
    def _validate_sumoql_syntax(self, query: str) -> Dict[str, Any]:
        """Validate SumoQL query syntax.
        
        Args:
            query: SumoQL query string
            
        Returns:
            Dictionary containing SumoQL validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check for basic SumoQL structure
        query_lower = query.lower()
        
        # Check for required elements in log queries
        if not any(keyword in query_lower for keyword in ['_sourcehost', '_sourcename', '_sourcecategory', '_index', '*']):
            validation_result["warnings"].append("Query may be too restrictive - consider adding source filters")
        
        # Check for potentially expensive operations
        if 'parse regex' in query_lower and 'where' not in query_lower:
            validation_result["warnings"].append("Regex parsing without WHERE clause may be expensive")
        
        # Check for proper aggregation in monitor queries
        if not any(agg in query_lower for agg in ['count', 'sum', 'avg', 'max', 'min', 'timeslice']):
            validation_result["warnings"].append("Monitor queries typically need aggregation functions")
        
        # Check for balanced parentheses
        if query.count('(') != query.count(')'):
            validation_result["errors"].append("Unbalanced parentheses in query")
        
        # Check for balanced quotes
        single_quotes = query.count("'") - query.count("\\'")
        double_quotes = query.count('"') - query.count('\\"')
        if single_quotes % 2 != 0:
            validation_result["errors"].append("Unbalanced single quotes in query")
        if double_quotes % 2 != 0:
            validation_result["errors"].append("Unbalanced double quotes in query")
        
        return validation_result
    
    def _validate_metrics_query_syntax(self, query: str) -> Dict[str, Any]:
        """Validate metrics query syntax.
        
        Args:
            query: Metrics query string
            
        Returns:
            Dictionary containing metrics validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        query_lower = query.lower()
        
        # Check for metric() function
        if 'metric=' not in query_lower and 'metric(' not in query_lower:
            validation_result["errors"].append("Metrics queries must include metric specification")
        
        # Check for proper aggregation
        if not any(agg in query_lower for agg in ['avg', 'sum', 'max', 'min', 'count', 'quantize']):
            validation_result["warnings"].append("Metrics queries typically need aggregation functions")
        
        # Check for time quantization
        if 'quantize' not in query_lower:
            validation_result["warnings"].append("Consider using quantize() for better performance in metrics queries")
        
        return validation_result
    
    def _validate_sli_query_syntax(self, query: str) -> Dict[str, Any]:
        """Validate SLI query syntax.
        
        Args:
            query: SLI query string
            
        Returns:
            Dictionary containing SLI validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        query_lower = query.lower()
        
        # SLI queries should have success and total calculations
        if 'success' not in query_lower and 'error' not in query_lower:
            validation_result["warnings"].append("SLI queries typically define success or error conditions")
        
        # Check for ratio calculations
        if '/' not in query and 'ratio' not in query_lower:
            validation_result["warnings"].append("SLI queries typically calculate success/total ratios")
        
        return validation_result
    
    def _check_common_query_issues(self, query: str) -> List[str]:
        """Check for common query issues that might affect performance or accuracy.
        
        Args:
            query: Query string to check
            
        Returns:
            List of warning messages for common issues
        """
        warnings = []
        query_lower = query.lower()
        
        # Check for wildcard usage
        if query.count('*') > 5:
            warnings.append("Excessive wildcard usage may impact query performance")
        
        # Check for very broad time ranges in relative queries
        if any(broad_range in query_lower for broad_range in ['-30d', '-60d', '-90d']):
            warnings.append("Very broad time ranges may impact query performance")
        
        # Check for missing field extraction
        if 'json' in query_lower and 'auto' not in query_lower and '|' not in query:
            warnings.append("JSON parsing without field extraction may be inefficient")
        
        # Check for potential case sensitivity issues
        if any(case_sensitive in query for case_sensitive in ['WHERE', 'AND', 'OR']):
            warnings.append("Consider using lowercase operators for consistency")
        
        return warnings
    
    def _validate_trigger_conditions(self, trigger_conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Validate trigger condition configurations.
        
        Args:
            trigger_conditions: Dictionary of trigger conditions by severity level
            
        Returns:
            Dictionary containing trigger validation results
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        if not trigger_conditions:
            validation_result["errors"].append("At least one trigger condition must be specified")
            validation_result["valid"] = False
            return validation_result
        
        # Validate each trigger condition
        valid_trigger_types = ["Critical", "Warning", "MissingData"]
        
        for trigger_type, condition in trigger_conditions.items():
            if trigger_type not in valid_trigger_types:
                validation_result["errors"].append(f"Invalid trigger type: {trigger_type}")
                validation_result["valid"] = False
                continue
            
            # Validate trigger condition structure
            condition_validation = self._validate_single_trigger_condition(trigger_type, condition)
            validation_result["errors"].extend(condition_validation.get("errors", []))
            validation_result["warnings"].extend(condition_validation.get("warnings", []))
            if condition_validation.get("errors"):
                validation_result["valid"] = False
        
        # Cross-validate trigger conditions
        cross_trigger_validation = self._cross_validate_trigger_conditions(trigger_conditions)
        validation_result["warnings"].extend(cross_trigger_validation.get("warnings", []))
        
        # Check for recommended trigger configurations
        if "Critical" not in trigger_conditions:
            validation_result["warnings"].append("Consider adding a Critical trigger condition for high-severity alerts")
        
        return validation_result
    
    def _validate_single_trigger_condition(self, trigger_type: str, condition: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single trigger condition.
        
        Args:
            trigger_type: Type of trigger (Critical, Warning, MissingData)
            condition: Trigger condition configuration
            
        Returns:
            Dictionary containing validation results for this trigger
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Required fields
        required_fields = ["threshold", "threshold_type", "time_range"]
        for field in required_fields:
            if field not in condition:
                validation_result["errors"].append(f"{trigger_type} trigger missing required field: {field}")
        
        # Validate threshold
        if "threshold" in condition:
            threshold = condition["threshold"]
            if not isinstance(threshold, (int, float)):
                validation_result["errors"].append(f"{trigger_type} trigger threshold must be a number")
            elif threshold < 0:
                validation_result["warnings"].append(f"{trigger_type} trigger has negative threshold, ensure this is intended")
        
        # Validate threshold_type
        if "threshold_type" in condition:
            valid_threshold_types = ["GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual"]
            if condition["threshold_type"] not in valid_threshold_types:
                validation_result["errors"].append(
                    f"{trigger_type} trigger has invalid threshold_type. Must be one of: {', '.join(valid_threshold_types)}"
                )
        
        # Validate time_range
        if "time_range" in condition:
            time_range = condition["time_range"]
            if not self._validate_time_range_format(time_range):
                validation_result["errors"].append(f"{trigger_type} trigger has invalid time_range format: {time_range}")
        
        # Validate optional fields
        if "occurrence_type" in condition:
            valid_occurrence_types = ["ResultCount", "AtLeastOnce", "Always"]
            if condition["occurrence_type"] not in valid_occurrence_types:
                validation_result["errors"].append(
                    f"{trigger_type} trigger has invalid occurrence_type. Must be one of: {', '.join(valid_occurrence_types)}"
                )
        
        if "trigger_source" in condition:
            valid_trigger_sources = ["AllResults", "AnyTimeSeries", "AllTimeSeries"]
            if condition["trigger_source"] not in valid_trigger_sources:
                validation_result["errors"].append(
                    f"{trigger_type} trigger has invalid trigger_source. Must be one of: {', '.join(valid_trigger_sources)}"
                )
        
        return validation_result
    
    def _validate_time_range_format(self, time_range: str) -> bool:
        """Validate time range format.
        
        Args:
            time_range: Time range string (e.g., '-5m', '-1h')
            
        Returns:
            True if format is valid, False otherwise
        """
        import re
        # Allow relative time expressions like -5m, -1h, -1d
        pattern = r'^-?\d+[smhdw]$'
        return bool(re.match(pattern, time_range))
    
    def _cross_validate_trigger_conditions(self, trigger_conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Perform cross-validation between trigger conditions.
        
        Args:
            trigger_conditions: Dictionary of all trigger conditions
            
        Returns:
            Dictionary containing cross-validation warnings
        """
        validation_result = {
            "warnings": []
        }
        
        # Check for logical threshold ordering
        if "Critical" in trigger_conditions and "Warning" in trigger_conditions:
            critical_threshold = trigger_conditions["Critical"].get("threshold")
            warning_threshold = trigger_conditions["Warning"].get("threshold")
            critical_type = trigger_conditions["Critical"].get("threshold_type", "GreaterThan")
            warning_type = trigger_conditions["Warning"].get("threshold_type", "GreaterThan")
            
            if (critical_threshold is not None and warning_threshold is not None and 
                critical_type == warning_type):
                
                if critical_type in ["GreaterThan", "GreaterThanOrEqual"]:
                    if critical_threshold <= warning_threshold:
                        validation_result["warnings"].append(
                            "Critical threshold should be higher than Warning threshold for GreaterThan comparisons"
                        )
                elif critical_type in ["LessThan", "LessThanOrEqual"]:
                    if critical_threshold >= warning_threshold:
                        validation_result["warnings"].append(
                            "Critical threshold should be lower than Warning threshold for LessThan comparisons"
                        )
        
        return validation_result 
   
    async def _validate_notification_configurations(self, notifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate notification configuration and setup.
        
        Args:
            notifications: List of notification action configurations
            
        Returns:
            Dictionary containing notification validation results
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        if not notifications:
            validation_result["warnings"].append("No notification actions configured - alerts will not be sent")
            return validation_result
        
        # Validate each notification configuration
        for i, notification in enumerate(notifications):
            notification_validation = await self._validate_single_notification(i, notification)
            validation_result["errors"].extend(notification_validation.get("errors", []))
            validation_result["warnings"].extend(notification_validation.get("warnings", []))
            if notification_validation.get("errors"):
                validation_result["valid"] = False
        
        # Perform cross-notification validation
        cross_notification_validation = self._cross_validate_notifications(notifications)
        validation_result["warnings"].extend(cross_notification_validation.get("warnings", []))
        
        return validation_result
    
    async def _validate_single_notification(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single notification action configuration.
        
        Args:
            index: Index of notification in the list (for error reporting)
            notification: Notification configuration dictionary
            
        Returns:
            Dictionary containing validation results for this notification
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check for required action_type field
        if "action_type" not in notification:
            validation_result["errors"].append(f"Notification {index + 1}: Missing required 'action_type' field")
            return validation_result
        
        action_type = notification["action_type"]
        valid_action_types = ["EmailAction", "WebhookAction", "SlackAction", "PagerDutyAction"]
        
        if action_type not in valid_action_types:
            validation_result["errors"].append(
                f"Notification {index + 1}: Invalid action_type '{action_type}'. Must be one of: {', '.join(valid_action_types)}"
            )
            return validation_result
        
        # Validate based on notification type
        if action_type == "EmailAction":
            email_validation = await self._validate_email_notification(index, notification)
            validation_result["errors"].extend(email_validation.get("errors", []))
            validation_result["warnings"].extend(email_validation.get("warnings", []))
            
        elif action_type == "WebhookAction":
            webhook_validation = await self._validate_webhook_notification(index, notification)
            validation_result["errors"].extend(webhook_validation.get("errors", []))
            validation_result["warnings"].extend(webhook_validation.get("warnings", []))
            
        elif action_type == "SlackAction":
            slack_validation = await self._validate_slack_notification(index, notification)
            validation_result["errors"].extend(slack_validation.get("errors", []))
            validation_result["warnings"].extend(slack_validation.get("warnings", []))
            
        elif action_type == "PagerDutyAction":
            pagerduty_validation = await self._validate_pagerduty_notification(index, notification)
            validation_result["errors"].extend(pagerduty_validation.get("errors", []))
            validation_result["warnings"].extend(pagerduty_validation.get("warnings", []))
        
        # Validate common notification fields
        common_validation = self._validate_common_notification_fields(index, notification)
        validation_result["errors"].extend(common_validation.get("errors", []))
        validation_result["warnings"].extend(common_validation.get("warnings", []))
        
        return validation_result
    
    async def _validate_email_notification(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate email notification configuration.
        
        Args:
            index: Notification index for error reporting
            notification: Email notification configuration
            
        Returns:
            Dictionary containing email validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check for recipients
        recipients = notification.get("recipients", [])
        if not recipients:
            validation_result["errors"].append(f"Email notification {index + 1}: No recipients specified")
            return validation_result
        
        if not isinstance(recipients, list):
            validation_result["errors"].append(f"Email notification {index + 1}: Recipients must be a list")
            return validation_result
        
        # Validate email addresses
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        for i, email in enumerate(recipients):
            if not isinstance(email, str):
                validation_result["errors"].append(f"Email notification {index + 1}: Recipient {i + 1} must be a string")
                continue
                
            if not re.match(email_pattern, email.strip()):
                validation_result["errors"].append(f"Email notification {index + 1}: Invalid email address '{email}'")
        
        # Check for reasonable number of recipients
        if len(recipients) > 50:
            validation_result["warnings"].append(f"Email notification {index + 1}: Large number of recipients ({len(recipients)}) may cause delivery issues")
        
        return validation_result
    
    async def _validate_webhook_notification(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate webhook notification configuration.
        
        Args:
            index: Notification index for error reporting
            notification: Webhook notification configuration
            
        Returns:
            Dictionary containing webhook validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check for webhook URL
        webhook_url = notification.get("webhook_url")
        if not webhook_url:
            validation_result["errors"].append(f"Webhook notification {index + 1}: Missing required 'webhook_url' field")
            return validation_result
        
        if not isinstance(webhook_url, str):
            validation_result["errors"].append(f"Webhook notification {index + 1}: webhook_url must be a string")
            return validation_result
        
        webhook_url = webhook_url.strip()
        
        # Validate URL format
        if not webhook_url.startswith(('http://', 'https://')):
            validation_result["errors"].append(f"Webhook notification {index + 1}: webhook_url must start with http:// or https://")
        
        # Recommend HTTPS for security
        if webhook_url.startswith('http://'):
            validation_result["warnings"].append(f"Webhook notification {index + 1}: Consider using HTTPS for better security")
        
        # Basic URL validation
        try:
            from urllib.parse import urlparse
            parsed = urlparse(webhook_url)
            if not parsed.netloc:
                validation_result["errors"].append(f"Webhook notification {index + 1}: Invalid webhook URL format")
        except Exception:
            validation_result["errors"].append(f"Webhook notification {index + 1}: Invalid webhook URL format")
        
        # Test webhook connectivity (optional, can be disabled for performance)
        # This is commented out as it would make network calls during validation
        # webhook_test = await self._test_webhook_connectivity(webhook_url)
        # if not webhook_test["reachable"]:
        #     validation_result["warnings"].append(f"Webhook notification {index + 1}: Webhook URL may not be reachable")
        
        return validation_result
    
    async def _validate_slack_notification(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Slack notification configuration.
        
        Args:
            index: Notification index for error reporting
            notification: Slack notification configuration
            
        Returns:
            Dictionary containing Slack validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # For Slack notifications, we typically need either a webhook URL or channel configuration
        webhook_url = notification.get("webhook_url")
        channel = notification.get("channel")
        
        if not webhook_url and not channel:
            validation_result["errors"].append(f"Slack notification {index + 1}: Must specify either 'webhook_url' or 'channel'")
            return validation_result
        
        # Validate webhook URL if provided
        if webhook_url:
            if not isinstance(webhook_url, str):
                validation_result["errors"].append(f"Slack notification {index + 1}: webhook_url must be a string")
            elif not webhook_url.strip().startswith('https://hooks.slack.com/'):
                validation_result["warnings"].append(f"Slack notification {index + 1}: webhook_url should be a Slack webhook URL")
        
        # Validate channel if provided
        if channel:
            if not isinstance(channel, str):
                validation_result["errors"].append(f"Slack notification {index + 1}: channel must be a string")
            else:
                channel = channel.strip()
                if not channel.startswith('#') and not channel.startswith('@'):
                    validation_result["warnings"].append(f"Slack notification {index + 1}: channel should start with # for channels or @ for users")
        
        return validation_result
    
    async def _validate_pagerduty_notification(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate PagerDuty notification configuration.
        
        Args:
            index: Notification index for error reporting
            notification: PagerDuty notification configuration
            
        Returns:
            Dictionary containing PagerDuty validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check for integration key
        integration_key = notification.get("integration_key")
        if not integration_key:
            validation_result["errors"].append(f"PagerDuty notification {index + 1}: Missing required 'integration_key' field")
            return validation_result
        
        if not isinstance(integration_key, str):
            validation_result["errors"].append(f"PagerDuty notification {index + 1}: integration_key must be a string")
            return validation_result
        
        integration_key = integration_key.strip()
        
        # Validate integration key format (PagerDuty keys are typically 32 characters)
        if len(integration_key) != 32:
            validation_result["warnings"].append(f"PagerDuty notification {index + 1}: integration_key should be 32 characters long")
        
        # Check for valid characters (alphanumeric)
        if not integration_key.replace('-', '').replace('_', '').isalnum():
            validation_result["warnings"].append(f"PagerDuty notification {index + 1}: integration_key contains unexpected characters")
        
        return validation_result
    
    def _validate_common_notification_fields(self, index: int, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Validate common notification fields like subject and message body.
        
        Args:
            index: Notification index for error reporting
            notification: Notification configuration
            
        Returns:
            Dictionary containing common field validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Validate subject if provided
        subject = notification.get("subject")
        if subject is not None:
            if not isinstance(subject, str):
                validation_result["errors"].append(f"Notification {index + 1}: subject must be a string")
            elif len(subject.strip()) == 0:
                validation_result["warnings"].append(f"Notification {index + 1}: subject is empty")
            elif len(subject) > 255:
                validation_result["errors"].append(f"Notification {index + 1}: subject is too long (maximum 255 characters)")
        
        # Validate message body if provided
        message_body = notification.get("message_body")
        if message_body is not None:
            if not isinstance(message_body, str):
                validation_result["errors"].append(f"Notification {index + 1}: message_body must be a string")
            elif len(message_body) > 2000:
                validation_result["errors"].append(f"Notification {index + 1}: message_body is too long (maximum 2000 characters)")
            elif len(message_body.strip()) == 0:
                validation_result["warnings"].append(f"Notification {index + 1}: message_body is empty")
        
        return validation_result
    
    def _cross_validate_notifications(self, notifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform cross-validation between notification configurations.
        
        Args:
            notifications: List of all notification configurations
            
        Returns:
            Dictionary containing cross-validation warnings
        """
        validation_result = {
            "warnings": []
        }
        
        # Check for duplicate notification destinations
        seen_destinations = set()
        for i, notification in enumerate(notifications):
            action_type = notification.get("action_type")
            
            # Create a destination identifier based on type and key fields
            if action_type == "EmailAction":
                recipients = notification.get("recipients", [])
                for recipient in recipients:
                    dest_id = f"email:{recipient}"
                    if dest_id in seen_destinations:
                        validation_result["warnings"].append(f"Duplicate email recipient '{recipient}' found in multiple notifications")
                    seen_destinations.add(dest_id)
                    
            elif action_type == "WebhookAction":
                webhook_url = notification.get("webhook_url")
                if webhook_url:
                    dest_id = f"webhook:{webhook_url}"
                    if dest_id in seen_destinations:
                        validation_result["warnings"].append(f"Duplicate webhook URL found in multiple notifications")
                    seen_destinations.add(dest_id)
                    
            elif action_type == "SlackAction":
                webhook_url = notification.get("webhook_url")
                channel = notification.get("channel")
                if webhook_url:
                    dest_id = f"slack_webhook:{webhook_url}"
                    if dest_id in seen_destinations:
                        validation_result["warnings"].append(f"Duplicate Slack webhook URL found in multiple notifications")
                    seen_destinations.add(dest_id)
                if channel:
                    dest_id = f"slack_channel:{channel}"
                    if dest_id in seen_destinations:
                        validation_result["warnings"].append(f"Duplicate Slack channel '{channel}' found in multiple notifications")
                    seen_destinations.add(dest_id)
                    
            elif action_type == "PagerDutyAction":
                integration_key = notification.get("integration_key")
                if integration_key:
                    dest_id = f"pagerduty:{integration_key}"
                    if dest_id in seen_destinations:
                        validation_result["warnings"].append(f"Duplicate PagerDuty integration key found in multiple notifications")
                    seen_destinations.add(dest_id)
        
        # Check for notification diversity
        action_types = [notif.get("action_type") for notif in notifications]
        unique_types = set(action_types)
        
        if len(notifications) > 3 and len(unique_types) == 1:
            validation_result["warnings"].append("Consider using different notification types for better redundancy")
        
        return validation_result
    
    def _perform_cross_validation_checks(
        self,
        config: 'MonitorConfig',
        trigger_conditions: Dict[str, Any],
        notifications: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform cross-validation checks between different configuration components.
        
        Args:
            config: Monitor configuration
            trigger_conditions: Trigger conditions
            notifications: Notification configurations
            
        Returns:
            Dictionary containing cross-validation results
        """
        validation_result = {
            "errors": [],
            "warnings": []
        }
        
        # Check if critical triggers have appropriate notifications
        if "Critical" in trigger_conditions and notifications:
            # Recommend having immediate notification types for critical alerts
            immediate_types = ["PagerDutyAction", "SlackAction"]
            has_immediate = any(notif.get("action_type") in immediate_types for notif in notifications)
            if not has_immediate:
                validation_result["warnings"].append("Critical triggers should have immediate notification types (PagerDuty, Slack)")
        
        # Check evaluation delay vs trigger time ranges
        evaluation_delay = config.evaluation_delay
        if evaluation_delay and evaluation_delay != "0m":
            # Parse evaluation delay
            try:
                delay_minutes = self._parse_time_to_minutes(evaluation_delay)
                for trigger_type, condition in trigger_conditions.items():
                    time_range = condition.get("time_range", "-5m")
                    range_minutes = self._parse_time_to_minutes(time_range.lstrip('-'))
                    
                    if delay_minutes >= range_minutes:
                        validation_result["warnings"].append(
                            f"{trigger_type} trigger time range ({time_range}) should be longer than evaluation delay ({evaluation_delay})"
                        )
            except Exception:
                # If parsing fails, skip this validation
                pass
        
        # Check monitor type vs query compatibility
        monitor_type = config.type.value
        query_lower = config.query.lower()
        
        if monitor_type == "MetricsMonitor" and "metric" not in query_lower:
            validation_result["warnings"].append("Metrics monitor should use metrics queries with metric() function")
        elif monitor_type == "MonitorsLibraryMonitor" and "metric" in query_lower:
            validation_result["warnings"].append("Log monitor should not use metrics queries")
        
        return validation_result
    
    def _parse_time_to_minutes(self, time_str: str) -> int:
        """Parse time string to minutes.
        
        Args:
            time_str: Time string like '5m', '1h', '2d'
            
        Returns:
            Time in minutes
        """
        time_str = time_str.strip().lower()
        if time_str.endswith('s'):
            return int(time_str[:-1]) / 60
        elif time_str.endswith('m'):
            return int(time_str[:-1])
        elif time_str.endswith('h'):
            return int(time_str[:-1]) * 60
        elif time_str.endswith('d'):
            return int(time_str[:-1]) * 24 * 60
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    
    def _format_monitor_creation_response(
        self,
        created_monitor: Dict[str, Any],
        validation_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format the monitor creation response with validation details.
        
        Args:
            created_monitor: Monitor data returned from API
            validation_results: Validation results from comprehensive validation
            
        Returns:
            Formatted response dictionary
        """
        return {
            "success": True,
            "monitor": {
                "id": created_monitor.get("id"),
                "name": created_monitor.get("name"),
                "description": created_monitor.get("description", ""),
                "type": self._convert_monitor_type_to_friendly(created_monitor.get("monitorType")),
                "api_type": created_monitor.get("monitorType"),
                "status": "disabled" if created_monitor.get("isDisabled") else "enabled",
                "created_at": created_monitor.get("createdAt"),
                "created_by": created_monitor.get("createdBy"),
                "version": created_monitor.get("version", 1)
            },
            "validation": {
                "query_syntax_valid": validation_results.get("query_syntax_valid"),
                "trigger_conditions_valid": validation_results.get("trigger_conditions_valid"),
                "notifications_valid": validation_results.get("notifications_valid"),
                "warnings": validation_results.get("warnings", []),
                "warning_count": len(validation_results.get("warnings", []))
            },
            "configuration_summary": {
                "trigger_count": len(created_monitor.get("triggers", [])),
                "notification_count": len(created_monitor.get("notifications", [])),
                "has_critical_trigger": any(
                    trigger.get("triggerType") == "Critical" 
                    for trigger in created_monitor.get("triggers", [])
                ),
                "evaluation_delay": created_monitor.get("evaluationDelay", "0m")
            },
            "next_steps": self._generate_next_steps_recommendations(created_monitor, validation_results)
        }
    
    def _generate_next_steps_recommendations(
        self,
        created_monitor: Dict[str, Any],
        validation_results: Dict[str, Any]
    ) -> List[str]:
        """Generate next steps recommendations for the created monitor.
        
        Args:
            created_monitor: Created monitor data
            validation_results: Validation results
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # Basic recommendations
        if created_monitor.get("isDisabled"):
            recommendations.append("Enable the monitor when ready to start monitoring")
        else:
            recommendations.append("Monitor is active and will start evaluating immediately")
        
        # Validation-based recommendations
        warnings = validation_results.get("warnings", [])
        if warnings:
            recommendations.append(f"Review {len(warnings)} configuration warnings for optimization opportunities")
        
        # Configuration-based recommendations
        if not created_monitor.get("notifications"):
            recommendations.append("Add notification actions to receive alerts when triggers fire")
        
        if not any(trigger.get("triggerType") == "Critical" for trigger in created_monitor.get("triggers", [])):
            recommendations.append("Consider adding a Critical trigger condition for high-severity alerts")
        
        # Monitoring recommendations
        recommendations.append("Test the monitor by checking its status and alert history")
        recommendations.append("Document the monitor's purpose and expected behavior for your team")
        
        return recommendations

    async def delete_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Delete specified monitor permanently with safety checks and audit trail.
        
        This method implements monitor deletion with comprehensive safety checks including:
        - Retrieving monitor information before deletion for audit trail
        - Handling deletion errors and monitor not found cases
        - Cascade deletion for associated notifications and history
        - Detailed confirmation with deleted monitor information
        
        Args:
            monitor_id: Unique identifier for the monitor to delete
            
        Returns:
            Dictionary containing deletion confirmation and deleted monitor details
            
        Raises:
            MonitorValidationError: If monitor_id is invalid or empty
            MonitorNotFoundError: If monitor doesn't exist
            MonitorPermissionError: If insufficient permissions
            MonitorOperationError: If deletion conflicts exist
            MonitorError: If monitor deletion fails
        """
        async def _delete_monitor_impl():
            # Validate monitor_id with enhanced validation
            validated_monitor_id = await validate_monitor_id(monitor_id, "delete_monitor")
            
            # Step 1: Retrieve monitor information before deletion for audit trail
            monitor_info = None
            try:
                monitor_info_response = await self.get_monitor(validated_monitor_id)
                monitor_info = monitor_info_response.get("monitor", monitor_info_response)
                
                logger.info(
                    "Retrieved monitor information for deletion audit trail",
                    extra={
                        "monitor_id": validated_monitor_id,
                        "monitor_name": monitor_info.get("name"),
                        "monitor_type": monitor_info.get("type"),
                        "is_disabled": monitor_info.get("status") == "disabled"
                    }
                )
                
            except MonitorNotFoundError:
                # Monitor doesn't exist - we'll still attempt deletion to get proper API response
                logger.warning(
                    f"Monitor {validated_monitor_id} not found during pre-deletion check, "
                    "proceeding with deletion attempt for proper error handling"
                )
                monitor_info = {
                    "id": validated_monitor_id,
                    "name": "Unknown (monitor not found)",
                    "type": "Unknown",
                    "status": "unknown"
                }
            except Exception as e:
                # For other errors during retrieval, we should still attempt deletion
                logger.warning(
                    f"Failed to retrieve monitor {validated_monitor_id} before deletion: {str(e)}",
                    extra={"error_type": type(e).__name__}
                )
                monitor_info = {
                    "id": validated_monitor_id,
                    "name": "Unknown (retrieval failed)",
                    "type": "Unknown",
                    "status": "unknown"
                }
            
            # Step 2: Perform the deletion via API client with error handling
            try:
                deletion_result = await self.api_client.delete_monitor(validated_monitor_id)
            except APIError as e:
                # The error handler will convert this to appropriate monitor error
                raise e
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while deleting monitor '{validated_monitor_id}': {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "delete_monitor",
                        monitor_id=validated_monitor_id,
                        monitor_name=monitor_info.get("name") if monitor_info else None
                    )
                ) from e
            
            # Step 3: Handle cascade deletion information
            try:
                cascade_info = await self._handle_cascade_deletion_info(monitor_info)
            except Exception as e:
                logger.warning(
                    "Failed to gather cascade deletion information",
                    extra={"monitor_id": validated_monitor_id, "error": str(e)}
                )
                cascade_info = {
                    "removed_items": [],
                    "cascade_status": "information_unavailable",
                    "error": str(e)
                }
            
            # Step 4: Format comprehensive deletion confirmation response
            try:
                response = {
                    "success": True,
                    "message": f"Monitor '{monitor_info.get('name', validated_monitor_id)}' deleted successfully",
                    "deleted_monitor": {
                        "id": validated_monitor_id,
                        "name": monitor_info.get("name", "Unknown"),
                        "type": monitor_info.get("type", "Unknown"),
                        "was_disabled": monitor_info.get("status") == "disabled",
                        "deletion_timestamp": datetime.now().isoformat()
                    },
                    "audit_trail": {
                        "deleted_by": "MCP Monitor Tools",
                        "deletion_method": "API",
                        "pre_deletion_status": monitor_info.get("status", "unknown")
                    },
                    "cascade_deletion": cascade_info,
                    "confirmation": {
                        "monitor_permanently_deleted": True,
                        "associated_data_removed": True,
                        "action_irreversible": True
                    }
                }
            except Exception as e:
                # If response formatting fails, return basic confirmation
                logger.warning(
                    "Monitor deleted successfully but response formatting failed",
                    extra={"monitor_id": validated_monitor_id, "format_error": str(e)}
                )
                response = {
                    "success": True,
                    "message": f"Monitor {validated_monitor_id} deleted successfully",
                    "deleted_monitor": {"id": validated_monitor_id},
                    "formatting_warning": f"Response formatting failed: {str(e)}"
                }
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "delete_monitor",
            _delete_monitor_impl,
            monitor_id=monitor_id,
            timeout_override=20.0
        )
        logger.info(
            "Deleting monitor with safety checks and audit trail",
            extra={"monitor_id": monitor_id, "operation": "delete_monitor"}
        )
        
        # Validate monitor_id parameter
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id,
                context={
                    "operation": "delete_monitor",
                    "suggestion": "Provide a valid monitor ID to delete"
                }
            )
        
        monitor_id = monitor_id.strip()
        
        try:
            # Step 1: Retrieve monitor information before deletion for audit trail
            logger.debug(f"Retrieving monitor information before deletion: {monitor_id}")
            
            try:
                monitor_info_response = await self.get_monitor(monitor_id)
                
                if not monitor_info_response.get("success", True):
                    raise APIError(
                        f"Failed to retrieve monitor {monitor_id} before deletion",
                        context={"monitor_id": monitor_id, "operation": "pre_delete_retrieval"}
                    )
                
                monitor_info = monitor_info_response.get("monitor", monitor_info_response)
                
                logger.info(
                    "Retrieved monitor information for deletion audit trail",
                    extra={
                        "monitor_id": monitor_id,
                        "monitor_name": monitor_info.get("name"),
                        "monitor_type": monitor_info.get("monitorType"),
                        "is_disabled": monitor_info.get("isDisabled"),
                        "trigger_count": len(monitor_info.get("triggers", [])),
                        "notification_count": len(monitor_info.get("notifications", []))
                    }
                )
                
            except APIError as e:
                # If monitor doesn't exist, we'll still attempt deletion to get proper API error
                if hasattr(e, 'status_code') and e.status_code == 404:
                    logger.warning(
                        f"Monitor {monitor_id} not found during pre-deletion check, proceeding with deletion attempt"
                    )
                    monitor_info = {
                        "id": monitor_id,
                        "name": "Unknown (monitor not found)",
                        "monitorType": "Unknown",
                        "isDisabled": None,
                        "triggers": [],
                        "notifications": []
                    }
                else:
                    # For other API errors, re-raise as they indicate a more serious issue
                    logger.error(
                        f"Failed to retrieve monitor {monitor_id} before deletion",
                        extra={"error": str(e), "status_code": getattr(e, 'status_code', None)}
                    )
                    raise APIError(
                        f"Cannot delete monitor {monitor_id}: failed to retrieve monitor information: {e.message}",
                        status_code=getattr(e, 'status_code', None),
                        context={
                            "monitor_id": monitor_id,
                            "operation": "pre_delete_retrieval",
                            "error_type": "retrieval_failed"
                        }
                    ) from e
            
            # Step 2: Perform the deletion via API client
            logger.info(f"Proceeding with monitor deletion: {monitor_id}")
            
            deletion_result = await self.api_client.delete_monitor(monitor_id)
            
            # Step 3: Handle deletion errors and monitor not found cases
            if not deletion_result.get("success", False):
                error_message = deletion_result.get("message", "Unknown deletion error")
                logger.error(
                    f"Monitor deletion failed: {monitor_id}",
                    extra={
                        "error_message": error_message,
                        "deletion_result": deletion_result
                    }
                )
                raise APIError(
                    f"Failed to delete monitor {monitor_id}: {error_message}",
                    context={
                        "monitor_id": monitor_id,
                        "operation": "delete_monitor",
                        "deletion_result": deletion_result
                    }
                )
            
            # Step 4: Add cascade deletion information for associated notifications and history
            cascade_info = await self._handle_cascade_deletion_info(monitor_info)
            
            # Step 5: Format comprehensive deletion confirmation response
            response = {
                "success": True,
                "message": f"Monitor '{monitor_info.get('name', monitor_id)}' deleted successfully",
                "deleted_monitor": {
                    "id": monitor_id,
                    "name": monitor_info.get("name", "Unknown"),
                    "type": self._convert_monitor_type_to_friendly(monitor_info.get("monitorType", "Unknown")),
                    "was_disabled": monitor_info.get("isDisabled", False),
                    "deletion_timestamp": datetime.now().isoformat(),
                    "trigger_conditions_count": len(monitor_info.get("triggers", [])),
                    "notification_actions_count": len(monitor_info.get("notifications", []))
                },
                "audit_trail": {
                    "deleted_by": "MCP Monitor Tools",
                    "deletion_method": "API",
                    "pre_deletion_status": "enabled" if not monitor_info.get("isDisabled", False) else "disabled",
                    "had_active_triggers": len(monitor_info.get("triggers", [])) > 0,
                    "had_notifications": len(monitor_info.get("notifications", [])) > 0
                },
                "cascade_deletion": cascade_info,
                "confirmation": {
                    "monitor_permanently_deleted": True,
                    "associated_data_removed": True,
                    "action_irreversible": True
                }
            }
            
            logger.info(
                "Monitor deleted successfully with complete audit trail",
                extra={
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_info.get("name"),
                    "cascade_items": len(cascade_info.get("removed_items", [])),
                    "deletion_timestamp": response["deleted_monitor"]["deletion_timestamp"]
                }
            )
            
            return response
            
        except ValidationError:
            # Re-raise validation errors as-is
            raise
            
        except APIError as e:
            # Handle API-specific errors with enhanced context
            logger.error(
                "Failed to delete monitor via API",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "status_code": getattr(e, 'status_code', None)
                }
            )
            
            # Provide more specific error messages based on status code
            if hasattr(e, 'status_code'):
                if e.status_code == 404:
                    raise ValidationError(
                        f"Monitor {monitor_id} not found - it may have already been deleted",
                        field_name="monitor_id",
                        field_value=monitor_id,
                        context={
                            "suggestion": "Verify the monitor ID is correct or check if it was already deleted",
                            "operation": "delete_monitor"
                        }
                    ) from e
                elif e.status_code == 403:
                    raise APIError(
                        f"Insufficient permissions to delete monitor {monitor_id}: {e.message}",
                        status_code=403,
                        context={
                            "operation": "delete_monitor",
                            "monitor_id": monitor_id,
                            "error_type": "permission_denied",
                            "suggestion": "Ensure you have the necessary permissions to delete monitors"
                        }
                    ) from e
                elif e.status_code == 409:
                    raise APIError(
                        f"Cannot delete monitor {monitor_id} due to conflicts: {e.message}",
                        status_code=409,
                        context={
                            "monitor_id": monitor_id,
                            "error_type": "deletion_conflict",
                            "suggestion": "The monitor may be referenced by other resources or currently active"
                        }
                    ) from e
            
            # Re-raise with enhanced context for other API errors
            raise APIError(
                f"Failed to delete monitor {monitor_id}: {e.message}",
                status_code=getattr(e, 'status_code', None),
                request_id=getattr(e, 'request_id', None),
                context={
                    "operation": "delete_monitor",
                    "monitor_id": monitor_id,
                    "error_type": "api_failure"
                }
            ) from e
            
        except Exception as e:
            logger.error(
                "Unexpected error deleting monitor",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise APIError(
                f"Unexpected error deleting monitor {monitor_id}: {str(e)}",
                context={
                    "operation": "delete_monitor",
                    "monitor_id": monitor_id,
                    "error_type": type(e).__name__
                }
            ) from e

    async def _handle_cascade_deletion_info(self, monitor_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle cascade deletion information for associated notifications and history.
        
        This method provides information about what associated data will be removed
        when a monitor is deleted, including notifications and historical data.
        
        Args:
            monitor_info: Monitor information retrieved before deletion
            
        Returns:
            Dictionary containing cascade deletion information
        """
        cascade_info = {
            "removed_items": [],
            "item_count": 0,
            "categories": {
                "notifications": 0,
                "triggers": 0,
                "history": "all_historical_data"
            }
        }
        
        try:
            # Count notification actions that will be removed
            notifications = monitor_info.get("notifications", [])
            if notifications:
                cascade_info["categories"]["notifications"] = len(notifications)
                cascade_info["removed_items"].extend([
                    f"Notification action: {notif.get('notification', {}).get('actionType', 'Unknown')}"
                    for notif in notifications
                ])
            
            # Count trigger conditions that will be removed
            triggers = monitor_info.get("triggers", [])
            if triggers:
                cascade_info["categories"]["triggers"] = len(triggers)
                cascade_info["removed_items"].extend([
                    f"Trigger condition: {trigger.get('triggerType', 'Unknown')}"
                    for trigger in triggers
                ])
            
            # Add information about historical data removal
            cascade_info["removed_items"].append("All historical execution data and alert history")
            cascade_info["removed_items"].append("All associated alert instances and status history")
            
            cascade_info["item_count"] = len(cascade_info["removed_items"])
            
            logger.debug(
                "Prepared cascade deletion information",
                extra={
                    "monitor_id": monitor_info.get("id"),
                    "total_items": cascade_info["item_count"],
                    "notifications": cascade_info["categories"]["notifications"],
                    "triggers": cascade_info["categories"]["triggers"]
                }
            )
            
        except Exception as e:
            logger.warning(
                "Error preparing cascade deletion information",
                extra={"error": str(e), "monitor_id": monitor_info.get("id")}
            )
            # Return basic cascade info even if detailed analysis fails
            cascade_info = {
                "removed_items": ["All associated monitor data and history"],
                "item_count": 1,
                "categories": {"note": "Detailed cascade analysis unavailable"}
            }
        
        return cascade_info
    
    async def get_monitor_status(
        self,
        monitor_id: Optional[str] = None,
        filter_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get current status of monitors and active alerts with comprehensive error handling.
        
        This method retrieves monitor status information for individual or all monitors,
        with optional filtering by status (triggered, normal, disabled, unknown).
        
        Args:
            monitor_id: Optional monitor ID to get status for specific monitor
            filter_status: Optional status filter (triggered, normal, disabled, unknown)
            
        Returns:
            Dictionary containing monitor status information with trigger timestamps and severity
            
        Raises:
            MonitorValidationError: If parameters are invalid
            MonitorNotFoundError: If monitor doesn't exist
            MonitorError: If status retrieval fails
            RateLimitError: If rate limit is exceeded
        """
        async def _get_monitor_status_impl():
            # Validate filter_status if provided
            if filter_status:
                valid_statuses = ["triggered", "normal", "disabled", "unknown"]
                if filter_status not in valid_statuses:
                    raise MonitorValidationError(
                        f"Invalid filter_status. Must be one of: {', '.join(valid_statuses)}",
                        field_name="filter_status",
                        field_value=filter_status,
                        context=create_monitor_error_context(
                            "get_monitor_status",
                            valid_statuses=valid_statuses
                        )
                    )
            
            # Validate monitor_id if provided
            validated_monitor_id = None
            if monitor_id:
                validated_monitor_id = await validate_monitor_id(monitor_id, "get_monitor_status")
            
            # Call API client to get monitor status with error handling
            try:
                api_response = await self.api_client.get_monitor_status(
                    monitor_id=validated_monitor_id,
                    filter_status=filter_status
                )
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while getting monitor status: {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "get_monitor_status",
                        monitor_id=validated_monitor_id,
                        filter_status=filter_status
                    )
                ) from e
            
            # Handle single monitor vs multiple monitors response
            if validated_monitor_id:
                # Single monitor status
                try:
                    status_data = api_response.get("data", {})
                    formatted_status = self._format_single_monitor_status(status_data, validated_monitor_id)
                    
                    response = {
                        "success": True,
                        "monitor_status": formatted_status,
                        "metadata": {
                            "monitor_id": validated_monitor_id,
                            "retrieved_at": datetime.now().isoformat(),
                            "status_type": "single_monitor"
                        }
                    }
                except Exception as e:
                    raise MonitorError(
                        f"Failed to format monitor status: {str(e)}",
                        monitor_id=validated_monitor_id,
                        operation="get_monitor_status",
                        context=create_monitor_error_context(
                            "get_monitor_status",
                            monitor_id=validated_monitor_id,
                            format_error=str(e)
                        )
                    ) from e
            else:
                # Multiple monitors status
                try:
                    status_list = api_response.get("data", [])
                    
                    # Apply client-side filtering if needed
                    if filter_status:
                        status_list = self._filter_status_by_condition(status_list, filter_status)
                    
                    # Format status information
                    formatted_statuses = []
                    for status in status_list:
                        try:
                            formatted_status = self._format_single_monitor_status(
                                status, status.get("monitorId")
                            )
                            formatted_statuses.append(formatted_status)
                        except Exception as e:
                            logger.warning(
                                f"Failed to format status for monitor {status.get('monitorId', 'unknown')}: {str(e)}",
                                extra={"monitor_id": status.get("monitorId"), "error": str(e)}
                            )
                            # Continue with other monitors
                            continue
                    
                    # Calculate status statistics
                    try:
                        status_stats = self._calculate_status_statistics(formatted_statuses)
                    except Exception as e:
                        logger.warning(
                            f"Failed to calculate status statistics: {str(e)}",
                            extra={"status_count": len(formatted_statuses)}
                        )
                        status_stats = {"total": len(formatted_statuses)}
                    
                    response = {
                        "success": True,
                        "monitor_statuses": formatted_statuses,
                        "metadata": {
                            "total_monitors": len(formatted_statuses),
                            "filter_applied": filter_status,
                            "retrieved_at": datetime.now().isoformat(),
                            "status_type": "multiple_monitors"
                        },
                        "statistics": status_stats
                    }
                except Exception as e:
                    raise MonitorError(
                        f"Failed to process monitor statuses: {str(e)}",
                        operation="get_monitor_status",
                        context=create_monitor_error_context(
                            "get_monitor_status",
                            filter_status=filter_status,
                            processing_error=str(e)
                        )
                    ) from e
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "get_monitor_status",
            _get_monitor_status_impl,
            monitor_id=monitor_id,
            timeout_override=25.0
        )
        logger.info(
            "Getting monitor status",
            extra={
                "monitor_id": monitor_id,
                "filter_status": filter_status
            }
        )
        
        # Validate filter_status if provided
        if filter_status:
            valid_statuses = ["triggered", "normal", "disabled", "unknown"]
            if filter_status not in valid_statuses:
                raise ValidationError(
                    f"Invalid filter_status. Must be one of: {', '.join(valid_statuses)}",
                    field_name="filter_status",
                    field_value=filter_status
                )
        
        # Validate monitor_id if provided
        if monitor_id and not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        try:
            # Call API client to get monitor status
            api_response = await self.api_client.get_monitor_status(
                monitor_id=monitor_id,
                filter_status=filter_status
            )
            
            # Handle single monitor vs multiple monitors response
            if monitor_id:
                # Single monitor status
                status_data = api_response.get("data", {})
                formatted_status = self._format_single_monitor_status(status_data, monitor_id)
                
                response = {
                    "success": True,
                    "monitor_status": formatted_status,
                    "metadata": {
                        "monitor_id": monitor_id,
                        "retrieved_at": datetime.now().isoformat(),
                        "status_type": "single_monitor"
                    }
                }
            else:
                # Multiple monitors status
                status_list = api_response.get("data", [])
                
                # Apply client-side filtering if needed
                if filter_status:
                    status_list = self._filter_status_by_condition(status_list, filter_status)
                
                # Format status information
                formatted_statuses = [
                    self._format_single_monitor_status(status, status.get("monitorId"))
                    for status in status_list
                ]
                
                # Calculate status statistics
                status_stats = self._calculate_status_statistics(formatted_statuses)
                
                response = {
                    "success": True,
                    "monitor_statuses": formatted_statuses,
                    "metadata": {
                        "total_monitors": len(formatted_statuses),
                        "retrieved_at": datetime.now().isoformat(),
                        "status_type": "multiple_monitors",
                        "filter_applied": filter_status
                    },
                    "statistics": status_stats
                }
            
            logger.info(
                "Successfully retrieved monitor status",
                extra={
                    "monitor_id": monitor_id,
                    "status_count": 1 if monitor_id else len(formatted_statuses),
                    "filter_status": filter_status
                }
            )
            
            return response
            
        except APIError as e:
            logger.error(
                "Failed to get monitor status",
                extra={
                    "error": str(e),
                    "monitor_id": monitor_id,
                    "filter_status": filter_status
                }
            )
            
            # Handle specific error cases
            if e.status_code == 404:
                raise APIError(
                    f"Monitor not found: {monitor_id}" if monitor_id else "Monitor status endpoint not found",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "get_monitor_status",
                        "monitor_id": monitor_id
                    }
                ) from e
            elif e.status_code == 403:
                raise APIError(
                    f"Insufficient permissions to access monitor status" + (f" for monitor {monitor_id}" if monitor_id else ""),
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "get_monitor_status",
                        "monitor_id": monitor_id
                    }
                ) from e
            else:
                raise APIError(
                    f"Failed to get monitor status: {e.message}",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "get_monitor_status",
                        "monitor_id": monitor_id
                    }
                ) from e
        
        except Exception as e:
            logger.error(
                "Unexpected error getting monitor status",
                extra={"error": str(e), "error_type": type(e).__name__}
            )
            raise APIError(
                f"Unexpected error getting monitor status: {str(e)}",
                context={"operation": "get_monitor_status"}
            ) from e
    
    def _format_single_monitor_status(self, status_data: Dict[str, Any], monitor_id: str) -> Dict[str, Any]:
        """Format single monitor status information with trigger timestamps and severity.
        
        Args:
            status_data: Raw status data from API
            monitor_id: Monitor ID for context
            
        Returns:
            Formatted monitor status information
        """
        try:
            # Extract basic status information
            monitor_name = status_data.get("monitorName", "Unknown")
            current_status = status_data.get("status", "Unknown")
            
            # Map API status to our enum values
            status_mapping = {
                "Normal": MonitorStatus.NORMAL,
                "Triggered": MonitorStatus.TRIGGERED,
                "Disabled": MonitorStatus.DISABLED,
                "Unknown": MonitorStatus.UNKNOWN
            }
            
            normalized_status = status_mapping.get(current_status, MonitorStatus.UNKNOWN)
            
            # Extract trigger information
            last_triggered = status_data.get("lastTriggered")
            current_trigger_severity = status_data.get("currentTriggerSeverity")
            trigger_count_24h = status_data.get("triggerCount24h", 0)
            
            # Extract evaluation timing
            last_evaluation = status_data.get("lastEvaluation")
            next_evaluation = status_data.get("nextEvaluation")
            
            # Format timestamps for better readability
            formatted_status = {
                "monitor_id": monitor_id,
                "monitor_name": monitor_name,
                "status": normalized_status.value,
                "status_description": self._get_status_description(normalized_status, current_trigger_severity),
                "last_triggered": self._format_timestamp_with_relative(last_triggered),
                "trigger_count_24h": trigger_count_24h,
                "current_trigger_severity": current_trigger_severity,
                "last_evaluation": self._format_timestamp_with_relative(last_evaluation),
                "next_evaluation": self._format_timestamp_with_relative(next_evaluation),
                "health_indicators": self._generate_status_health_indicators(
                    normalized_status, trigger_count_24h, last_triggered
                )
            }
            
            # Add trigger details if currently triggered
            if normalized_status == MonitorStatus.TRIGGERED and current_trigger_severity:
                formatted_status["trigger_details"] = self._extract_trigger_details(status_data)
            
            return formatted_status
            
        except Exception as e:
            logger.warning(
                "Error formatting monitor status",
                extra={"error": str(e), "monitor_id": monitor_id}
            )
            # Return basic status information if formatting fails
            return {
                "monitor_id": monitor_id,
                "monitor_name": status_data.get("monitorName", "Unknown"),
                "status": status_data.get("status", "Unknown"),
                "status_description": "Status information partially unavailable",
                "error": f"Formatting error: {str(e)}"
            }
    
    def _filter_status_by_condition(self, status_list: List[Dict[str, Any]], filter_status: str) -> List[Dict[str, Any]]:
        """Filter status list by status condition.
        
        Args:
            status_list: List of status dictionaries
            filter_status: Status filter to apply
            
        Returns:
            Filtered list of status dictionaries
        """
        status_filter_map = {
            "triggered": lambda s: s.get("status") == "Triggered",
            "normal": lambda s: s.get("status") == "Normal",
            "disabled": lambda s: s.get("status") == "Disabled",
            "unknown": lambda s: s.get("status") == "Unknown"
        }
        
        filter_func = status_filter_map.get(filter_status)
        if filter_func:
            return [status for status in status_list if filter_func(status)]
        
        return status_list
    
    def _calculate_status_statistics(self, formatted_statuses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate statistics for monitor status information.
        
        Args:
            formatted_statuses: List of formatted status dictionaries
            
        Returns:
            Dictionary containing status statistics
        """
        total_monitors = len(formatted_statuses)
        
        if total_monitors == 0:
            return {
                "total_monitors": 0,
                "status_breakdown": {},
                "alert_summary": {
                    "total_triggers_24h": 0,
                    "monitors_with_alerts": 0,
                    "severity_breakdown": {}
                }
            }
        
        # Count by status
        status_counts = {}
        total_triggers_24h = 0
        monitors_with_alerts = 0
        severity_counts = {}
        
        for status in formatted_statuses:
            # Count status types
            status_type = status.get("status", "Unknown")
            status_counts[status_type] = status_counts.get(status_type, 0) + 1
            
            # Count triggers
            trigger_count = status.get("trigger_count_24h", 0)
            total_triggers_24h += trigger_count
            if trigger_count > 0:
                monitors_with_alerts += 1
            
            # Count severity levels for triggered monitors
            if status_type == "Triggered":
                severity = status.get("current_trigger_severity", "Unknown")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        return {
            "total_monitors": total_monitors,
            "status_breakdown": status_counts,
            "alert_summary": {
                "total_triggers_24h": total_triggers_24h,
                "monitors_with_alerts": monitors_with_alerts,
                "average_triggers_per_monitor": round(total_triggers_24h / total_monitors, 2),
                "severity_breakdown": severity_counts
            },
            "health_score": self._calculate_overall_health_score(status_counts, total_monitors)
        }
    
    def _get_status_description(self, status: MonitorStatus, severity: Optional[str] = None) -> str:
        """Get human-readable status description.
        
        Args:
            status: Monitor status enum
            severity: Current trigger severity if applicable
            
        Returns:
            Human-readable status description
        """
        descriptions = {
            MonitorStatus.NORMAL: "Monitor is operating normally with no active alerts",
            MonitorStatus.DISABLED: "Monitor is disabled and not evaluating conditions",
            MonitorStatus.UNKNOWN: "Monitor status could not be determined"
        }
        
        if status == MonitorStatus.TRIGGERED:
            if severity:
                return f"Monitor is currently triggered with {severity} severity alert"
            else:
                return "Monitor is currently triggered with active alert"
        
        return descriptions.get(status, "Status information unavailable")
    
    def _format_timestamp_with_relative(self, timestamp: Optional[str]) -> Optional[Dict[str, Any]]:
        """Format timestamp with both absolute and relative time information.
        
        Args:
            timestamp: ISO timestamp string
            
        Returns:
            Dictionary with formatted timestamp information or None
        """
        if not timestamp:
            return None
        
        try:
            from datetime import datetime, timezone
            import dateutil.parser
            
            # Parse the timestamp
            dt = dateutil.parser.parse(timestamp)
            
            # Calculate relative time
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            time_diff = now - dt
            relative_time = self._format_relative_time(time_diff)
            
            return {
                "absolute": timestamp,
                "relative": relative_time,
                "formatted": dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            
        except Exception as e:
            logger.warning(f"Error formatting timestamp {timestamp}: {e}")
            return {
                "absolute": timestamp,
                "relative": "unknown",
                "formatted": timestamp
            }
    
    def _format_relative_time(self, time_diff) -> str:
        """Format time difference as relative time string.
        
        Args:
            time_diff: timedelta object
            
        Returns:
            Human-readable relative time string
        """
        total_seconds = int(time_diff.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds} seconds ago"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = total_seconds // 86400
            return f"{days} day{'s' if days != 1 else ''} ago"
    
    def _generate_status_health_indicators(
        self,
        status: MonitorStatus,
        trigger_count_24h: int,
        last_triggered: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate health indicators for monitor status.
        
        Args:
            status: Monitor status
            trigger_count_24h: Number of triggers in last 24 hours
            last_triggered: Last trigger timestamp information
            
        Returns:
            Dictionary containing health indicators
        """
        indicators = {
            "overall_health": "unknown",
            "stability": "unknown",
            "alert_frequency": "unknown",
            "recommendations": []
        }
        
        try:
            # Determine overall health
            if status == MonitorStatus.NORMAL:
                if trigger_count_24h == 0:
                    indicators["overall_health"] = "excellent"
                elif trigger_count_24h <= 2:
                    indicators["overall_health"] = "good"
                else:
                    indicators["overall_health"] = "fair"
            elif status == MonitorStatus.TRIGGERED:
                indicators["overall_health"] = "poor"
            elif status == MonitorStatus.DISABLED:
                indicators["overall_health"] = "disabled"
            else:
                indicators["overall_health"] = "unknown"
            
            # Determine stability
            if trigger_count_24h == 0:
                indicators["stability"] = "stable"
            elif trigger_count_24h <= 3:
                indicators["stability"] = "mostly_stable"
            elif trigger_count_24h <= 10:
                indicators["stability"] = "unstable"
            else:
                indicators["stability"] = "very_unstable"
            
            # Determine alert frequency
            if trigger_count_24h == 0:
                indicators["alert_frequency"] = "none"
            elif trigger_count_24h <= 2:
                indicators["alert_frequency"] = "low"
            elif trigger_count_24h <= 5:
                indicators["alert_frequency"] = "moderate"
            else:
                indicators["alert_frequency"] = "high"
            
            # Generate recommendations
            if status == MonitorStatus.TRIGGERED:
                indicators["recommendations"].append("Investigate current alert and resolve underlying issue")
            
            if trigger_count_24h > 5:
                indicators["recommendations"].append("Consider adjusting trigger thresholds to reduce alert noise")
            
            if status == MonitorStatus.DISABLED:
                indicators["recommendations"].append("Review if monitor should be re-enabled")
            
            if trigger_count_24h == 0 and last_triggered:
                indicators["recommendations"].append("Monitor appears stable - consider if thresholds are appropriate")
            
        except Exception as e:
            logger.warning(f"Error generating health indicators: {e}")
            indicators["error"] = str(e)
        
        return indicators
    
    def _extract_trigger_details(self, status_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract detailed trigger information for currently triggered monitors.
        
        Args:
            status_data: Raw status data from API
            
        Returns:
            Dictionary containing trigger details
        """
        try:
            trigger_details = {
                "severity": status_data.get("currentTriggerSeverity"),
                "triggered_at": status_data.get("lastTriggered"),
                "trigger_value": status_data.get("currentTriggerValue"),
                "threshold": status_data.get("triggerThreshold"),
                "condition": status_data.get("triggerCondition"),
                "duration": None
            }
            
            # Calculate trigger duration if we have the timestamp
            if trigger_details["triggered_at"]:
                try:
                    from datetime import datetime, timezone
                    import dateutil.parser
                    
                    triggered_dt = dateutil.parser.parse(trigger_details["triggered_at"])
                    now = datetime.now(timezone.utc)
                    if triggered_dt.tzinfo is None:
                        triggered_dt = triggered_dt.replace(tzinfo=timezone.utc)
                    
                    duration = now - triggered_dt
                    trigger_details["duration"] = self._format_relative_time(duration)
                    
                except Exception as e:
                    logger.warning(f"Error calculating trigger duration: {e}")
            
            return trigger_details
            
        except Exception as e:
            logger.warning(f"Error extracting trigger details: {e}")
            return {"error": f"Could not extract trigger details: {str(e)}"}
    
    def _calculate_overall_health_score(self, status_counts: Dict[str, int], total_monitors: int) -> Dict[str, Any]:
        """Calculate overall health score for all monitors.
        
        Args:
            status_counts: Count of monitors by status
            total_monitors: Total number of monitors
            
        Returns:
            Dictionary containing health score information
        """
        if total_monitors == 0:
            return {"score": 0, "grade": "N/A", "description": "No monitors to evaluate"}
        
        # Calculate weighted score
        weights = {
            "Normal": 100,
            "Disabled": 50,  # Neutral - not good or bad
            "Triggered": 0,
            "Unknown": 25
        }
        
        total_score = 0
        for status, count in status_counts.items():
            weight = weights.get(status, 0)
            total_score += weight * count
        
        health_score = total_score / total_monitors
        
        # Determine grade
        if health_score >= 90:
            grade = "A"
            description = "Excellent - Most monitors are healthy"
        elif health_score >= 80:
            grade = "B"
            description = "Good - Minor issues detected"
        elif health_score >= 70:
            grade = "C"
            description = "Fair - Some monitors need attention"
        elif health_score >= 60:
            grade = "D"
            description = "Poor - Multiple monitors have issues"
        else:
            grade = "F"
            description = "Critical - Significant monitoring problems"
        
        return {
            "score": round(health_score, 1),
            "grade": grade,
            "description": description
        }
    
    async def get_active_alerts(
        self,
        severity: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get all currently active alerts with comprehensive error handling.
        
        This method retrieves all active alerts across monitors with optional filtering
        by severity level. Results are sorted by severity and trigger time for priority handling.
        
        Args:
            severity: Optional severity filter (Critical, Warning, MissingData)
            limit: Maximum number of alerts to return (1-1000)
            
        Returns:
            Dictionary containing active alerts with trigger details and context
            
        Raises:
            MonitorValidationError: If parameters are invalid
            MonitorError: If alert retrieval fails
            RateLimitError: If rate limit is exceeded
        """
        async def _get_active_alerts_impl():
            # Validate limit parameter
            if limit < 1 or limit > 1000:
                raise MonitorValidationError(
                    "Limit must be between 1 and 1000",
                    field_name="limit",
                    field_value=limit,
                    context=create_monitor_error_context("get_active_alerts")
                )
            
            # Validate severity if provided
            if severity:
                valid_severities = ["Critical", "Warning", "MissingData"]
                if severity not in valid_severities:
                    raise MonitorValidationError(
                        f"Invalid severity. Must be one of: {', '.join(valid_severities)}",
                        field_name="severity",
                        field_value=severity,
                        context=create_monitor_error_context(
                            "get_active_alerts",
                            valid_severities=valid_severities
                        )
                    )
            
            # Call API client to get active alerts with error handling
            try:
                api_response = await self.api_client.get_active_alerts(
                    severity=severity,
                    limit=limit
                )
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while getting active alerts: {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "get_active_alerts",
                        severity=severity,
                        limit=limit
                    )
                ) from e
            
            # Extract alerts from response
            alerts_data = api_response.get("data", [])
            total_count = api_response.get("total", len(alerts_data))
            
            # Handle case with no active alerts
            if not alerts_data:
                return self._format_no_alerts_response(severity, total_count)
            
            # Format alerts with error handling for individual alerts
            formatted_alerts = []
            formatting_errors = []
            
            for i, alert_data in enumerate(alerts_data):
                try:
                    formatted_alert = self._format_single_alert(alert_data)
                    formatted_alerts.append(formatted_alert)
                except Exception as e:
                    formatting_errors.append({
                        "index": i,
                        "alert_id": alert_data.get("alertId", "unknown"),
                        "error": str(e)
                    })
                    logger.warning(
                        f"Failed to format alert {alert_data.get('alertId', 'unknown')}: {str(e)}",
                        extra={"alert_data": alert_data, "error": str(e)}
                    )
                    # Continue with other alerts
                    continue
            
            if not formatted_alerts and formatting_errors:
                raise MonitorError(
                    f"Failed to format any alerts: {len(formatting_errors)} formatting errors",
                    operation="get_active_alerts",
                    context=create_monitor_error_context(
                        "get_active_alerts",
                        formatting_errors=formatting_errors,
                        total_alerts=len(alerts_data)
                    )
                )
            
            # Sort alerts by severity and trigger time
            try:
                sorted_alerts = self._sort_alerts_by_priority(formatted_alerts)
            except Exception as e:
                logger.warning(
                    f"Failed to sort alerts by priority: {str(e)}",
                    extra={"alert_count": len(formatted_alerts)}
                )
                sorted_alerts = formatted_alerts  # Use unsorted alerts
            
            # Calculate alert statistics
            try:
                alert_stats = self._calculate_alert_statistics(sorted_alerts)
            except Exception as e:
                logger.warning(
                    f"Failed to calculate alert statistics: {str(e)}",
                    extra={"alert_count": len(sorted_alerts)}
                )
                alert_stats = {"total": len(sorted_alerts)}
            
            response = {
                "success": True,
                "active_alerts": sorted_alerts,
                "metadata": {
                    "total_alerts": total_count,
                    "returned_count": len(sorted_alerts),
                    "severity_filter": severity,
                    "limit": limit,
                    "retrieved_at": datetime.now().isoformat()
                },
                "statistics": alert_stats
            }
            
            # Add formatting warnings if any
            if formatting_errors:
                response["warnings"] = {
                    "formatting_errors": len(formatting_errors),
                    "message": f"{len(formatting_errors)} alerts could not be formatted and were skipped"
                }
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "get_active_alerts",
            _get_active_alerts_impl,
            timeout_override=20.0
        )
        logger.info(
            "Getting active alerts",
            extra={
                "severity": severity,
                "limit": limit
            }
        )
        
        # Validate parameters
        if limit < 1 or limit > 1000:
            raise ValidationError(
                "Limit must be between 1 and 1000",
                field_name="limit",
                field_value=limit
            )
        
        # Validate severity if provided
        if severity:
            valid_severities = ["Critical", "Warning", "MissingData"]
            if severity not in valid_severities:
                raise ValidationError(
                    f"Invalid severity. Must be one of: {', '.join(valid_severities)}",
                    field_name="severity",
                    field_value=severity
                )
        
        try:
            # Call API client to get active alerts
            api_response = await self.api_client.get_active_alerts(
                severity=severity,
                limit=limit
            )
            
            # Extract alerts from response
            alerts_data = api_response.get("data", [])
            total_count = api_response.get("total", len(alerts_data))
            
            # Handle case with no active alerts
            if not alerts_data:
                return self._format_no_alerts_response(severity, total_count)
            
            # Format and sort alerts
            formatted_alerts = [
                self._format_single_alert(alert_data)
                for alert_data in alerts_data
            ]
            
            # Sort alerts by severity and trigger time
            sorted_alerts = self._sort_alerts_by_priority(formatted_alerts)
            
            # Calculate alert statistics
            alert_stats = self._calculate_alert_statistics(sorted_alerts)
            
            response = {
                "success": True,
                "active_alerts": sorted_alerts,
                "metadata": {
                    "total_alerts": total_count,
                    "returned_count": len(sorted_alerts),
                    "severity_filter": severity,
                    "retrieved_at": datetime.now().isoformat(),
                    "has_more": len(sorted_alerts) < total_count
                },
                "statistics": alert_stats,
                "summary": self._generate_alert_summary(sorted_alerts, alert_stats)
            }
            
            logger.info(
                "Successfully retrieved active alerts",
                extra={
                    "total_alerts": total_count,
                    "returned_count": len(sorted_alerts),
                    "severity_filter": severity
                }
            )
            
            return response
            
        except APIError as e:
            logger.error(
                "Failed to get active alerts",
                extra={
                    "error": str(e),
                    "severity": severity,
                    "limit": limit
                }
            )
            
            # Handle specific error cases
            if e.status_code == 403:
                raise APIError(
                    "Insufficient permissions to access active alerts",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "get_active_alerts",
                        "severity": severity
                    }
                ) from e
            else:
                raise APIError(
                    f"Failed to get active alerts: {e.message}",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "get_active_alerts",
                        "severity": severity
                    }
                ) from e
        
        except Exception as e:
            logger.error(
                "Unexpected error getting active alerts",
                extra={"error": str(e), "error_type": type(e).__name__}
            )
            raise APIError(
                f"Unexpected error getting active alerts: {str(e)}",
                context={"operation": "get_active_alerts"}
            ) from e
    
    def _format_no_alerts_response(self, severity: Optional[str], total_count: int) -> Dict[str, Any]:
        """Format response when no active alerts are found.
        
        Args:
            severity: Severity filter that was applied
            total_count: Total count from API response
            
        Returns:
            Formatted response for no alerts case
        """
        message = "No active alerts found"
        if severity:
            message += f" with {severity} severity"
        
        return {
            "success": True,
            "active_alerts": [],
            "metadata": {
                "total_alerts": total_count,
                "returned_count": 0,
                "severity_filter": severity,
                "retrieved_at": datetime.now().isoformat(),
                "has_more": False
            },
            "statistics": {
                "total_alerts": 0,
                "severity_breakdown": {},
                "monitors_with_alerts": 0,
                "average_alert_age": 0
            },
            "summary": {
                "message": message,
                "status": "healthy" if not severity else "filtered_healthy",
                "recommendations": [
                    "All monitors are operating normally" if not severity else f"No {severity} alerts currently active"
                ]
            }
        }
    
    def _format_single_alert(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format single alert information with trigger details and context.
        
        Args:
            alert_data: Raw alert data from API
            
        Returns:
            Formatted alert information
        """
        try:
            # Extract basic alert information
            alert_id = alert_data.get("alertId", "unknown")
            monitor_id = alert_data.get("monitorId", "unknown")
            monitor_name = alert_data.get("monitorName", "Unknown Monitor")
            severity = alert_data.get("severity", "Unknown")
            
            # Extract trigger information
            triggered_at = alert_data.get("triggeredAt")
            trigger_value = alert_data.get("triggerValue")
            threshold = alert_data.get("threshold")
            query = alert_data.get("query", "")
            
            # Format the alert
            formatted_alert = {
                "alert_id": alert_id,
                "monitor_id": monitor_id,
                "monitor_name": monitor_name,
                "severity": severity,
                "severity_priority": self._get_severity_priority(severity),
                "status": alert_data.get("status", "Active"),
                "triggered_at": self._format_timestamp_with_relative(triggered_at),
                "trigger_details": {
                    "value": trigger_value,
                    "threshold": threshold,
                    "comparison": self._format_threshold_comparison(trigger_value, threshold),
                    "query": query[:200] + "..." if len(query) > 200 else query
                },
                "alert_context": self._generate_alert_context(alert_data),
                "urgency_indicators": self._generate_urgency_indicators(severity, triggered_at, trigger_value, threshold)
            }
            
            # Add duration information
            if triggered_at:
                formatted_alert["duration"] = self._calculate_alert_duration(triggered_at)
            
            return formatted_alert
            
        except Exception as e:
            logger.warning(
                "Error formatting alert",
                extra={"error": str(e), "alert_id": alert_data.get("alertId")}
            )
            # Return basic alert information if formatting fails
            return {
                "alert_id": alert_data.get("alertId", "unknown"),
                "monitor_id": alert_data.get("monitorId", "unknown"),
                "monitor_name": alert_data.get("monitorName", "Unknown Monitor"),
                "severity": alert_data.get("severity", "Unknown"),
                "status": "Active",
                "error": f"Formatting error: {str(e)}"
            }
    
    def _sort_alerts_by_priority(self, alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort alerts by severity and trigger time for priority handling.
        
        Args:
            alerts: List of formatted alert dictionaries
            
        Returns:
            Sorted list of alerts (highest priority first)
        """
        def sort_key(alert):
            # Primary sort: severity priority (lower number = higher priority)
            severity_priority = alert.get("severity_priority", 999)
            
            # Secondary sort: trigger time (newer alerts first)
            triggered_at = alert.get("triggered_at", {})
            if isinstance(triggered_at, dict) and "absolute" in triggered_at:
                try:
                    import dateutil.parser
                    dt = dateutil.parser.parse(triggered_at["absolute"])
                    # Negative timestamp for reverse chronological order
                    time_priority = -dt.timestamp()
                except Exception:
                    time_priority = 0
            else:
                time_priority = 0
            
            return (severity_priority, time_priority)
        
        return sorted(alerts, key=sort_key)
    
    def _get_severity_priority(self, severity: str) -> int:
        """Get numeric priority for severity level (lower = higher priority).
        
        Args:
            severity: Severity level string
            
        Returns:
            Numeric priority value
        """
        priority_map = {
            "Critical": 1,
            "Warning": 2,
            "MissingData": 3
        }
        return priority_map.get(severity, 999)
    
    def _format_threshold_comparison(self, trigger_value: Optional[float], threshold: Optional[float]) -> str:
        """Format threshold comparison for human readability.
        
        Args:
            trigger_value: Value that triggered the alert
            threshold: Threshold that was exceeded
            
        Returns:
            Human-readable comparison string
        """
        if trigger_value is None or threshold is None:
            return "Comparison data unavailable"
        
        try:
            if trigger_value > threshold:
                percentage = ((trigger_value - threshold) / threshold) * 100
                return f"{trigger_value} exceeded threshold {threshold} by {percentage:.1f}%"
            elif trigger_value < threshold:
                percentage = ((threshold - trigger_value) / threshold) * 100
                return f"{trigger_value} fell below threshold {threshold} by {percentage:.1f}%"
            else:
                return f"{trigger_value} equals threshold {threshold}"
        except (ZeroDivisionError, TypeError):
            return f"{trigger_value} vs threshold {threshold}"
    
    def _generate_alert_context(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate contextual information for the alert.
        
        Args:
            alert_data: Raw alert data from API
            
        Returns:
            Dictionary containing alert context information
        """
        context = {
            "monitor_type": alert_data.get("monitorType", "Unknown"),
            "trigger_condition": alert_data.get("triggerCondition", {}),
            "notification_sent": alert_data.get("notificationSent", False),
            "escalation_level": alert_data.get("escalationLevel", 1),
            "related_alerts": alert_data.get("relatedAlerts", [])
        }
        
        # Add business impact assessment
        context["business_impact"] = self._assess_business_impact(
            alert_data.get("severity"),
            alert_data.get("monitorName", ""),
            alert_data.get("triggerValue")
        )
        
        return context
    
    def _generate_urgency_indicators(
        self,
        severity: str,
        triggered_at: Optional[str],
        trigger_value: Optional[float],
        threshold: Optional[float]
    ) -> Dict[str, Any]:
        """Generate urgency indicators for the alert.
        
        Args:
            severity: Alert severity level
            triggered_at: When the alert was triggered
            trigger_value: Value that triggered the alert
            threshold: Threshold that was exceeded
            
        Returns:
            Dictionary containing urgency indicators
        """
        indicators = {
            "urgency_level": "unknown",
            "response_time_recommendation": "unknown",
            "escalation_recommended": False,
            "factors": []
        }
        
        try:
            # Base urgency on severity
            if severity == "Critical":
                indicators["urgency_level"] = "high"
                indicators["response_time_recommendation"] = "immediate"
            elif severity == "Warning":
                indicators["urgency_level"] = "medium"
                indicators["response_time_recommendation"] = "within 30 minutes"
            else:
                indicators["urgency_level"] = "low"
                indicators["response_time_recommendation"] = "within 2 hours"
            
            # Adjust based on duration
            if triggered_at:
                duration_minutes = self._get_alert_duration_minutes(triggered_at)
                if duration_minutes > 60:  # Alert active for over 1 hour
                    indicators["escalation_recommended"] = True
                    indicators["factors"].append("Alert has been active for over 1 hour")
                
                if duration_minutes > 240:  # Alert active for over 4 hours
                    indicators["urgency_level"] = "critical"
                    indicators["factors"].append("Alert has been active for over 4 hours")
            
            # Adjust based on threshold breach severity
            if trigger_value is not None and threshold is not None and threshold != 0:
                breach_percentage = abs((trigger_value - threshold) / threshold) * 100
                if breach_percentage > 200:  # More than 200% breach
                    indicators["urgency_level"] = "critical"
                    indicators["factors"].append(f"Threshold breached by {breach_percentage:.0f}%")
                elif breach_percentage > 100:  # More than 100% breach
                    if indicators["urgency_level"] == "low":
                        indicators["urgency_level"] = "medium"
                    indicators["factors"].append(f"Significant threshold breach ({breach_percentage:.0f}%)")
            
        except Exception as e:
            logger.warning(f"Error generating urgency indicators: {e}")
            indicators["error"] = str(e)
        
        return indicators
    
    def _calculate_alert_duration(self, triggered_at: str) -> Dict[str, Any]:
        """Calculate how long the alert has been active.
        
        Args:
            triggered_at: ISO timestamp when alert was triggered
            
        Returns:
            Dictionary containing duration information
        """
        try:
            from datetime import datetime, timezone
            import dateutil.parser
            
            triggered_dt = dateutil.parser.parse(triggered_at)
            now = datetime.now(timezone.utc)
            if triggered_dt.tzinfo is None:
                triggered_dt = triggered_dt.replace(tzinfo=timezone.utc)
            
            duration = now - triggered_dt
            duration_minutes = int(duration.total_seconds() / 60)
            
            return {
                "total_minutes": duration_minutes,
                "human_readable": self._format_relative_time(duration),
                "is_stale": duration_minutes > 240,  # Over 4 hours
                "requires_attention": duration_minutes > 60  # Over 1 hour
            }
            
        except Exception as e:
            logger.warning(f"Error calculating alert duration: {e}")
            return {
                "total_minutes": 0,
                "human_readable": "unknown",
                "is_stale": False,
                "requires_attention": False,
                "error": str(e)
            }
    
    def _get_alert_duration_minutes(self, triggered_at: str) -> int:
        """Get alert duration in minutes.
        
        Args:
            triggered_at: ISO timestamp when alert was triggered
            
        Returns:
            Duration in minutes
        """
        try:
            from datetime import datetime, timezone
            import dateutil.parser
            
            triggered_dt = dateutil.parser.parse(triggered_at)
            now = datetime.now(timezone.utc)
            if triggered_dt.tzinfo is None:
                triggered_dt = triggered_dt.replace(tzinfo=timezone.utc)
            
            duration = now - triggered_dt
            return int(duration.total_seconds() / 60)
            
        except Exception:
            return 0
    
    def _calculate_alert_statistics(self, alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate statistics for active alerts.
        
        Args:
            alerts: List of formatted alert dictionaries
            
        Returns:
            Dictionary containing alert statistics
        """
        total_alerts = len(alerts)
        
        if total_alerts == 0:
            return {
                "total_alerts": 0,
                "severity_breakdown": {},
                "monitors_with_alerts": 0,
                "average_alert_age": 0,
                "urgency_breakdown": {}
            }
        
        # Count by severity
        severity_counts = {}
        urgency_counts = {}
        monitor_ids = set()
        total_duration_minutes = 0
        
        for alert in alerts:
            # Count severity
            severity = alert.get("severity", "Unknown")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            # Count urgency
            urgency = alert.get("urgency_indicators", {}).get("urgency_level", "unknown")
            urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1
            
            # Track unique monitors
            monitor_id = alert.get("monitor_id")
            if monitor_id:
                monitor_ids.add(monitor_id)
            
            # Sum duration for average
            duration = alert.get("duration", {}).get("total_minutes", 0)
            total_duration_minutes += duration
        
        average_age_minutes = total_duration_minutes / total_alerts if total_alerts > 0 else 0
        
        return {
            "total_alerts": total_alerts,
            "severity_breakdown": severity_counts,
            "urgency_breakdown": urgency_counts,
            "monitors_with_alerts": len(monitor_ids),
            "average_alert_age": {
                "minutes": round(average_age_minutes, 1),
                "human_readable": self._format_minutes_to_human(average_age_minutes)
            },
            "stale_alerts": len([a for a in alerts if a.get("duration", {}).get("is_stale", False)]),
            "critical_alerts": severity_counts.get("Critical", 0)
        }
    
    def _generate_alert_summary(self, alerts: List[Dict[str, Any]], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary information for active alerts.
        
        Args:
            alerts: List of formatted alert dictionaries
            stats: Alert statistics
            
        Returns:
            Dictionary containing alert summary
        """
        total_alerts = stats["total_alerts"]
        critical_count = stats.get("critical_alerts", 0)
        stale_count = stats.get("stale_alerts", 0)
        
        # Determine overall status
        if total_alerts == 0:
            status = "healthy"
            message = "No active alerts"
        elif critical_count > 0:
            status = "critical"
            message = f"{critical_count} critical alert{'s' if critical_count != 1 else ''} require immediate attention"
        elif stale_count > 0:
            status = "degraded"
            message = f"{stale_count} alert{'s' if stale_count != 1 else ''} have been active for over 4 hours"
        else:
            status = "warning"
            message = f"{total_alerts} active alert{'s' if total_alerts != 1 else ''}"
        
        # Generate recommendations
        recommendations = []
        if critical_count > 0:
            recommendations.append(f"Immediately investigate {critical_count} critical alert{'s' if critical_count != 1 else ''}")
        
        if stale_count > 0:
            recommendations.append(f"Review {stale_count} stale alert{'s' if stale_count != 1 else ''} - consider escalation or threshold adjustment")
        
        if total_alerts > 10:
            recommendations.append("High alert volume detected - consider reviewing monitor thresholds")
        
        if not recommendations and total_alerts > 0:
            recommendations.append("Monitor alerts and investigate root causes")
        
        return {
            "status": status,
            "message": message,
            "recommendations": recommendations,
            "priority_actions": self._generate_priority_actions(alerts)
        }
    
    def _assess_business_impact(self, severity: Optional[str], monitor_name: str, trigger_value: Optional[float]) -> str:
        """Assess potential business impact of the alert.
        
        Args:
            severity: Alert severity level
            monitor_name: Name of the monitor
            trigger_value: Value that triggered the alert
            
        Returns:
            Business impact assessment string
        """
        if severity == "Critical":
            return "High - Service disruption likely"
        elif severity == "Warning":
            return "Medium - Performance degradation possible"
        else:
            return "Low - Monitoring issue detected"
    
    def _format_minutes_to_human(self, minutes: float) -> str:
        """Format minutes to human-readable string.
        
        Args:
            minutes: Number of minutes
            
        Returns:
            Human-readable time string
        """
        if minutes < 1:
            return "less than 1 minute"
        elif minutes < 60:
            return f"{int(minutes)} minute{'s' if int(minutes) != 1 else ''}"
        elif minutes < 1440:  # Less than 24 hours
            hours = int(minutes / 60)
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = int(minutes / 1440)
            return f"{days} day{'s' if days != 1 else ''}"
    
    def _generate_priority_actions(self, alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate priority actions based on active alerts.
        
        Args:
            alerts: List of formatted alert dictionaries
            
        Returns:
            List of priority action dictionaries
        """
        actions = []
        
        # Find critical alerts
        critical_alerts = [a for a in alerts if a.get("severity") == "Critical"]
        if critical_alerts:
            actions.append({
                "priority": 1,
                "action": f"Investigate {len(critical_alerts)} critical alert{'s' if len(critical_alerts) != 1 else ''}",
                "alert_ids": [a["alert_id"] for a in critical_alerts[:3]],  # Top 3
                "urgency": "immediate"
            })
        
        # Find stale alerts
        stale_alerts = [a for a in alerts if a.get("duration", {}).get("is_stale", False)]
        if stale_alerts:
            actions.append({
                "priority": 2,
                "action": f"Review {len(stale_alerts)} stale alert{'s' if len(stale_alerts) != 1 else ''} (active >4h)",
                "alert_ids": [a["alert_id"] for a in stale_alerts[:3]],  # Top 3
                "urgency": "high"
            })
        
        # Find alerts requiring escalation
        escalation_alerts = [
            a for a in alerts 
            if a.get("urgency_indicators", {}).get("escalation_recommended", False)
        ]
        if escalation_alerts:
            actions.append({
                "priority": 3,
                "action": f"Consider escalating {len(escalation_alerts)} alert{'s' if len(escalation_alerts) != 1 else ''}",
                "alert_ids": [a["alert_id"] for a in escalation_alerts[:3]],  # Top 3
                "urgency": "medium"
            })
        
        return actions
    
    async def enable_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Enable specified monitor with comprehensive error handling.
        
        This method enables a disabled monitor, allowing it to resume normal monitoring
        operations and trigger conditions evaluation. The operation includes status
        change confirmation and validation.
        
        Args:
            monitor_id: Unique identifier for the monitor to enable
            
        Returns:
            Dictionary containing enable operation result with status confirmation
            
        Raises:
            MonitorValidationError: If monitor_id is invalid
            MonitorNotFoundError: If monitor doesn't exist
            MonitorPermissionError: If insufficient permissions
            MonitorOperationError: If enable operation fails
            MonitorError: If monitor operation fails
        """
        async def _enable_monitor_impl():
            # Validate monitor_id with enhanced validation
            validated_monitor_id = await validate_monitor_id(monitor_id, "enable_monitor")
            
            # Get current monitor status before enabling
            try:
                current_monitor = await self.api_client.get_monitor(validated_monitor_id)
                current_status = "disabled" if current_monitor.get("isDisabled", False) else "enabled"
                monitor_name = current_monitor.get("name", "Unknown")
            except APIError as e:
                # The error handler will convert this to appropriate monitor error
                raise e
            
            # Check if monitor is already enabled
            if current_status == "enabled":
                return {
                    "success": True,
                    "message": f"Monitor '{monitor_name}' is already enabled",
                    "monitor_id": validated_monitor_id,
                    "monitor_name": monitor_name,
                    "status_change": {
                        "previous_status": "enabled",
                        "new_status": "enabled",
                        "changed": False
                    },
                    "timestamp": datetime.now().isoformat(),
                    "no_action_required": True
                }
            
            # Enable the monitor via API
            try:
                enable_result = await self.api_client.enable_monitor(validated_monitor_id)
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while enabling monitor '{validated_monitor_id}': {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "enable_monitor",
                        monitor_id=validated_monitor_id,
                        monitor_name=monitor_name
                    )
                ) from e
            
            # Verify the status change
            try:
                updated_monitor = await self.api_client.get_monitor(validated_monitor_id)
                new_status = "disabled" if updated_monitor.get("isDisabled", False) else "enabled"
            except Exception as e:
                logger.warning(
                    "Failed to verify monitor status after enable operation",
                    extra={"monitor_id": validated_monitor_id, "error": str(e)}
                )
                new_status = "unknown"
            
            return {
                "success": True,
                "message": f"Monitor '{monitor_name}' enabled successfully",
                "monitor_id": validated_monitor_id,
                "monitor_name": monitor_name,
                "status_change": {
                    "previous_status": current_status,
                    "new_status": new_status,
                    "changed": True,
                    "change_timestamp": datetime.now().isoformat()
                },
                "operation_result": enable_result
            }
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "enable_monitor",
            _enable_monitor_impl,
            monitor_id=monitor_id,
            timeout_override=15.0
        )
        logger.info(
            "Enabling monitor",
            extra={"monitor_id": monitor_id}
        )
        
        # Validate monitor_id
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        try:
            # Get current monitor status before enabling
            try:
                current_monitor = await self.api_client.get_monitor(monitor_id)
                current_status = "disabled" if current_monitor.get("isDisabled", False) else "enabled"
                monitor_name = current_monitor.get("name", "Unknown")
            except APIError as e:
                if e.status_code == 404:
                    raise APIError(
                        f"Monitor with ID '{monitor_id}' not found",
                        status_code=404,
                        request_id=e.request_id,
                        context={
                            "operation": "enable_monitor",
                            "monitor_id": monitor_id
                        }
                    ) from e
                else:
                    raise
            
            # Check if monitor is already enabled
            if current_status == "enabled":
                logger.info(
                    "Monitor is already enabled",
                    extra={"monitor_id": monitor_id, "monitor_name": monitor_name}
                )
                return {
                    "success": True,
                    "message": f"Monitor '{monitor_name}' is already enabled",
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_name,
                    "status_change": {
                        "previous_status": "enabled",
                        "new_status": "enabled",
                        "changed": False
                    },
                    "timestamp": datetime.now().isoformat(),
                    "operation": "enable_monitor"
                }
            
            # Call API client to enable monitor
            api_response = await self.api_client.enable_monitor(monitor_id)
            
            # Format successful response with status change confirmation
            response = {
                "success": True,
                "message": f"Monitor '{monitor_name}' enabled successfully",
                "monitor_id": monitor_id,
                "monitor_name": monitor_name,
                "status_change": {
                    "previous_status": current_status,
                    "new_status": "enabled",
                    "changed": True,
                    "change_timestamp": api_response.get("timestamp", datetime.now().isoformat())
                },
                "timestamp": datetime.now().isoformat(),
                "operation": "enable_monitor",
                "details": {
                    "monitor_will_resume": "Monitor will resume evaluating trigger conditions",
                    "notifications_active": "Notifications will be sent when conditions are met",
                    "next_evaluation": "Monitor will be evaluated according to its schedule"
                }
            }
            
            logger.info(
                "Monitor enabled successfully",
                extra={
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_name,
                    "previous_status": current_status
                }
            )
            
            return response
            
        except APIError as e:
            logger.error(
                "Failed to enable monitor",
                extra={
                    "error": str(e),
                    "monitor_id": monitor_id,
                    "status_code": getattr(e, 'status_code', None)
                }
            )
            
            # Handle specific error cases
            if e.status_code == 403:
                raise APIError(
                    f"Insufficient permissions to enable monitor '{monitor_id}'",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "enable_monitor",
                        "monitor_id": monitor_id
                    }
                ) from e
            elif e.status_code == 404:
                # Already handled above, but include for completeness
                raise
            else:
                raise APIError(
                    f"Failed to enable monitor '{monitor_id}': {e.message}",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "enable_monitor",
                        "monitor_id": monitor_id
                    }
                ) from e
        
        except Exception as e:
            logger.error(
                "Unexpected error enabling monitor",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "monitor_id": monitor_id
                }
            )
            raise APIError(
                f"Unexpected error enabling monitor '{monitor_id}': {str(e)}",
                context={
                    "operation": "enable_monitor",
                    "monitor_id": monitor_id
                }
            ) from e
    
    async def disable_monitor(self, monitor_id: str) -> Dict[str, Any]:
        """Disable specified monitor with comprehensive error handling.
        
        This method disables an enabled monitor, stopping trigger condition evaluation
        while preserving the monitor configuration. The operation includes status
        change confirmation and validation.
        
        Args:
            monitor_id: Unique identifier for the monitor to disable
            
        Returns:
            Dictionary containing disable operation result with status confirmation
            
        Raises:
            MonitorValidationError: If monitor_id is invalid
            MonitorNotFoundError: If monitor doesn't exist
            MonitorPermissionError: If insufficient permissions
            MonitorOperationError: If disable operation fails
            MonitorError: If monitor operation fails
        """
        async def _disable_monitor_impl():
            # Validate monitor_id with enhanced validation
            validated_monitor_id = await validate_monitor_id(monitor_id, "disable_monitor")
            
            # Get current monitor status before disabling
            try:
                current_monitor = await self.api_client.get_monitor(validated_monitor_id)
                current_status = "disabled" if current_monitor.get("isDisabled", False) else "enabled"
                monitor_name = current_monitor.get("name", "Unknown")
            except APIError as e:
                # The error handler will convert this to appropriate monitor error
                raise e
            
            # Check if monitor is already disabled
            if current_status == "disabled":
                return {
                    "success": True,
                    "message": f"Monitor '{monitor_name}' is already disabled",
                    "monitor_id": validated_monitor_id,
                    "monitor_name": monitor_name,
                    "status_change": {
                        "previous_status": "disabled",
                        "new_status": "disabled",
                        "changed": False
                    },
                    "timestamp": datetime.now().isoformat(),
                    "no_action_required": True
                }
            
            # Disable the monitor via API
            try:
                disable_result = await self.api_client.disable_monitor(validated_monitor_id)
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while disabling monitor '{validated_monitor_id}': {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "disable_monitor",
                        monitor_id=validated_monitor_id,
                        monitor_name=monitor_name
                    )
                ) from e
            
            # Verify the status change
            try:
                updated_monitor = await self.api_client.get_monitor(validated_monitor_id)
                new_status = "disabled" if updated_monitor.get("isDisabled", False) else "enabled"
            except Exception as e:
                logger.warning(
                    "Failed to verify monitor status after disable operation",
                    extra={"monitor_id": validated_monitor_id, "error": str(e)}
                )
                new_status = "unknown"
            
            return {
                "success": True,
                "message": f"Monitor '{monitor_name}' disabled successfully",
                "monitor_id": validated_monitor_id,
                "monitor_name": monitor_name,
                "status_change": {
                    "previous_status": current_status,
                    "new_status": new_status,
                    "changed": True,
                    "change_timestamp": datetime.now().isoformat()
                },
                "operation_result": disable_result,
                "details": {
                    "monitor_stopped": "Monitor will stop evaluating trigger conditions",
                    "configuration_preserved": "Monitor configuration is preserved",
                    "can_be_re_enabled": "Monitor can be re-enabled at any time"
                }
            }
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "disable_monitor",
            _disable_monitor_impl,
            monitor_id=monitor_id,
            timeout_override=15.0
        )
        logger.info(
            "Disabling monitor",
            extra={"monitor_id": monitor_id}
        )
        
        # Validate monitor_id
        if not monitor_id or not monitor_id.strip():
            raise ValidationError(
                "Monitor ID cannot be empty",
                field_name="monitor_id",
                field_value=monitor_id
            )
        
        monitor_id = monitor_id.strip()
        
        try:
            # Get current monitor status before disabling
            try:
                current_monitor = await self.api_client.get_monitor(monitor_id)
                current_status = "disabled" if current_monitor.get("isDisabled", False) else "enabled"
                monitor_name = current_monitor.get("name", "Unknown")
            except APIError as e:
                if e.status_code == 404:
                    raise APIError(
                        f"Monitor with ID '{monitor_id}' not found",
                        status_code=404,
                        request_id=e.request_id,
                        context={
                            "operation": "disable_monitor",
                            "monitor_id": monitor_id
                        }
                    ) from e
                else:
                    raise
            
            # Check if monitor is already disabled
            if current_status == "disabled":
                logger.info(
                    "Monitor is already disabled",
                    extra={"monitor_id": monitor_id, "monitor_name": monitor_name}
                )
                return {
                    "success": True,
                    "message": f"Monitor '{monitor_name}' is already disabled",
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_name,
                    "status_change": {
                        "previous_status": "disabled",
                        "new_status": "disabled",
                        "changed": False
                    },
                    "timestamp": datetime.now().isoformat(),
                    "operation": "disable_monitor"
                }
            
            # Call API client to disable monitor
            api_response = await self.api_client.disable_monitor(monitor_id)
            
            # Format successful response with status change confirmation
            response = {
                "success": True,
                "message": f"Monitor '{monitor_name}' disabled successfully",
                "monitor_id": monitor_id,
                "monitor_name": monitor_name,
                "status_change": {
                    "previous_status": current_status,
                    "new_status": "disabled",
                    "changed": True,
                    "change_timestamp": api_response.get("timestamp", datetime.now().isoformat())
                },
                "timestamp": datetime.now().isoformat(),
                "operation": "disable_monitor",
                "details": {
                    "monitor_stopped": "Monitor will stop evaluating trigger conditions",
                    "notifications_paused": "No notifications will be sent while disabled",
                    "configuration_preserved": "Monitor configuration is preserved and can be re-enabled"
                }
            }
            
            logger.info(
                "Monitor disabled successfully",
                extra={
                    "monitor_id": monitor_id,
                    "monitor_name": monitor_name,
                    "previous_status": current_status
                }
            )
            
            return response
            
        except APIError as e:
            logger.error(
                "Failed to disable monitor",
                extra={
                    "error": str(e),
                    "monitor_id": monitor_id,
                    "status_code": getattr(e, 'status_code', None)
                }
            )
            
            # Handle specific error cases
            if e.status_code == 403:
                raise APIError(
                    f"Insufficient permissions to disable monitor '{monitor_id}'",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "disable_monitor",
                        "monitor_id": monitor_id
                    }
                ) from e
            elif e.status_code == 404:
                # Already handled above, but include for completeness
                raise
            else:
                raise APIError(
                    f"Failed to disable monitor '{monitor_id}': {e.message}",
                    status_code=e.status_code,
                    request_id=e.request_id,
                    context={
                        "operation": "disable_monitor",
                        "monitor_id": monitor_id
                    }
                ) from e
        
        except Exception as e:
            logger.error(
                "Unexpected error disabling monitor",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "monitor_id": monitor_id
                }
            )
            raise APIError(
                f"Unexpected error disabling monitor '{monitor_id}': {str(e)}",
                context={
                    "operation": "disable_monitor",
                    "monitor_id": monitor_id
                }
            ) from e

    async def validate_monitor_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate monitor configuration with comprehensive error handling.
        
        This method performs comprehensive validation of monitor configuration
        including query syntax validation using dry-run approach, trigger
        condition validation, and notification configuration validation.
        
        Args:
            config: Monitor configuration dictionary to validate
            
        Returns:
            Dictionary containing detailed validation results with warnings and errors
            
        Raises:
            MonitorValidationError: If config parameter is invalid
            MonitorConfigurationError: If configuration validation fails
            MonitorError: If validation process fails
        """
        async def _validate_monitor_config_impl():
            # Validate input parameter
            if not config or not isinstance(config, dict):
                raise MonitorValidationError(
                    "Configuration must be a non-empty dictionary",
                    field_name="config",
                    field_value=config,
                    context=create_monitor_error_context("validate_monitor_config")
                )
            
            # Initialize validation result
            validation_result = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "query_syntax_valid": None,
                "trigger_conditions_valid": None,
                "notifications_valid": None,
                "validation_details": {
                    "config_structure": None,
                    "query_validation": None,
                    "trigger_validation": None,
                    "notification_validation": None
                }
            }
            
            # Step 1: Validate configuration structure using Pydantic model
            try:
                monitor_config = MonitorConfig(**config)
                validation_result["validation_details"]["config_structure"] = {
                    "valid": True,
                    "message": "Configuration structure is valid"
                }
            except Exception as e:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Configuration structure error: {str(e)}")
                validation_result["validation_details"]["config_structure"] = {
                    "valid": False,
                    "error": str(e)
                }
                # Continue with other validations even if structure is invalid
            
            # Step 2: Validate query syntax using dry-run approach
            query = config.get("query", "")
            monitor_type = config.get("type", "MonitorsLibraryMonitor")
            
            if query:
                try:
                    query_validation = await self.api_client.validate_monitor_query(
                        query=query,
                        monitor_type=monitor_type
                    )
                    
                    validation_result["query_syntax_valid"] = query_validation.get("valid", False)
                    validation_result["validation_details"]["query_validation"] = query_validation
                    
                    if not query_validation.get("valid", False):
                        validation_result["valid"] = False
                        error_msg = query_validation.get("error", "Query syntax is invalid")
                        validation_result["errors"].append(f"Query validation error: {error_msg}")
                    
                except RateLimitError as e:
                    raise RateLimitError(
                        f"Rate limit exceeded during query validation: {e.message}",
                        retry_after=e.retry_after,
                        limit_type=e.limit_type,
                        context=create_monitor_error_context(
                            "validate_monitor_config",
                            query_length=len(query),
                            monitor_type=monitor_type
                        )
                    ) from e
                except Exception as e:
                    # If query validation API fails, log warning but don't fail entire validation
                    validation_result["warnings"].append(
                        f"Could not validate query syntax via API: {str(e)}"
                    )
                    validation_result["validation_details"]["query_validation"] = {
                        "valid": None,
                        "error": str(e),
                        "message": "Query validation skipped due to API error"
                    }
            else:
                validation_result["errors"].append("Query is required but not provided")
                validation_result["valid"] = False
            
            # Step 3: Validate trigger conditions
            trigger_conditions = config.get("trigger_conditions", {})
            if trigger_conditions:
                try:
                    trigger_validation = await self._validate_trigger_conditions_comprehensive(
                        trigger_conditions
                    )
                    
                    validation_result["trigger_conditions_valid"] = trigger_validation.get("valid", False)
                    validation_result["validation_details"]["trigger_validation"] = trigger_validation
                    
                    if not trigger_validation.get("valid", False):
                        validation_result["valid"] = False
                        validation_result["errors"].extend(trigger_validation.get("errors", []))
                    
                    # Add warnings from trigger validation
                    validation_result["warnings"].extend(trigger_validation.get("warnings", []))
                    
                except Exception as e:
                    validation_result["warnings"].append(
                        f"Could not validate trigger conditions: {str(e)}"
                    )
                    validation_result["validation_details"]["trigger_validation"] = {
                        "valid": None,
                        "error": str(e),
                        "message": "Trigger validation skipped due to error"
                    }
            else:
                validation_result["errors"].append("Trigger conditions are required but not provided")
                validation_result["valid"] = False
            
            # Step 4: Validate notification configurations
            notifications = config.get("notifications", [])
            if notifications:
                try:
                    notification_validation = await self._validate_notification_configurations(notifications)
                    
                    validation_result["notifications_valid"] = notification_validation.get("valid", False)
                    validation_result["validation_details"]["notification_validation"] = notification_validation
                    
                    if not notification_validation.get("valid", False):
                        validation_result["valid"] = False
                        validation_result["errors"].extend(notification_validation.get("errors", []))
                    
                    # Add warnings from notification validation
                    validation_result["warnings"].extend(notification_validation.get("warnings", []))
                    
                except Exception as e:
                    validation_result["warnings"].append(
                        f"Could not validate notification configurations: {str(e)}"
                    )
                    validation_result["validation_details"]["notification_validation"] = {
                        "valid": None,
                        "error": str(e),
                        "message": "Notification validation skipped due to error"
                    }
            
            # Step 5: Add overall validation summary
            validation_result["summary"] = {
                "total_errors": len(validation_result["errors"]),
                "total_warnings": len(validation_result["warnings"]),
                "validation_passed": validation_result["valid"],
                "config_ready_for_creation": validation_result["valid"] and len(validation_result["errors"]) == 0
            }
            
            return validation_result
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "validate_monitor_config",
            _validate_monitor_config_impl,
            timeout_override=10.0
        )
        logger.info("Starting monitor configuration validation")
        
        if not config or not isinstance(config, dict):
            raise ValidationError(
                "Configuration must be a non-empty dictionary",
                field_name="config",
                field_value=config
            )
        
        # Initialize validation result
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "query_syntax_valid": None,
            "trigger_conditions_valid": None,
            "notifications_valid": None,
            "validation_details": {
                "config_structure": None,
                "query_validation": None,
                "trigger_validation": None,
                "notification_validation": None
            }
        }
        
        try:
            # Step 1: Validate configuration structure using Pydantic model
            logger.debug("Validating configuration structure")
            try:
                monitor_config = MonitorConfig(**config)
                validation_result["validation_details"]["config_structure"] = {
                    "valid": True,
                    "message": "Configuration structure is valid"
                }
                logger.debug("Configuration structure validation passed")
            except Exception as e:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Configuration structure error: {str(e)}")
                validation_result["validation_details"]["config_structure"] = {
                    "valid": False,
                    "error": str(e)
                }
                logger.warning(f"Configuration structure validation failed: {str(e)}")
                # Continue with other validations even if structure is invalid
            
            # Step 2: Validate query syntax using dry-run approach
            logger.debug("Validating query syntax")
            query = config.get("query", "")
            monitor_type = config.get("type", "MonitorsLibraryMonitor")
            
            if query:
                try:
                    query_validation = await self.api_client.validate_monitor_query(
                        query=query,
                        monitor_type=monitor_type
                    )
                    
                    validation_result["query_syntax_valid"] = query_validation.get("valid", False)
                    validation_result["validation_details"]["query_validation"] = query_validation
                    
                    if not query_validation.get("valid", False):
                        validation_result["valid"] = False
                        error_msg = query_validation.get("error", "Query syntax is invalid")
                        validation_result["errors"].append(f"Query validation error: {error_msg}")
                        logger.warning(f"Query validation failed: {error_msg}")
                    else:
                        logger.debug("Query syntax validation passed")
                        
                except APIError as e:
                    # If query validation API fails, log warning but don't fail entire validation
                    validation_result["warnings"].append(
                        f"Could not validate query syntax via API: {str(e)}"
                    )
                    validation_result["validation_details"]["query_validation"] = {
                        "valid": None,
                        "error": f"API validation failed: {str(e)}",
                        "fallback_used": True
                    }
                    logger.warning(f"Query API validation failed, continuing: {str(e)}")
            else:
                validation_result["valid"] = False
                validation_result["errors"].append("Query is required but not provided")
                validation_result["query_syntax_valid"] = False
            
            # Step 3: Validate trigger conditions
            logger.debug("Validating trigger conditions")
            trigger_conditions = config.get("trigger_conditions", {})
            trigger_validation_result = self._validate_trigger_conditions(trigger_conditions)
            
            validation_result["trigger_conditions_valid"] = trigger_validation_result["valid"]
            validation_result["validation_details"]["trigger_validation"] = trigger_validation_result
            
            if not trigger_validation_result["valid"]:
                validation_result["valid"] = False
                validation_result["errors"].extend(trigger_validation_result["errors"])
            
            validation_result["warnings"].extend(trigger_validation_result.get("warnings", []))
            
            # Step 4: Validate notification configurations
            logger.debug("Validating notification configurations")
            notifications = config.get("notifications", [])
            notification_validation_result = self._validate_notification_configurations(notifications)
            
            validation_result["notifications_valid"] = notification_validation_result["valid"]
            validation_result["validation_details"]["notification_validation"] = notification_validation_result
            
            if not notification_validation_result["valid"]:
                validation_result["valid"] = False
                validation_result["errors"].extend(notification_validation_result["errors"])
            
            validation_result["warnings"].extend(notification_validation_result.get("warnings", []))
            
            # Step 5: Additional validation checks
            self._perform_additional_validation_checks(config, validation_result)
            
            # Final validation summary
            validation_result["summary"] = {
                "total_errors": len(validation_result["errors"]),
                "total_warnings": len(validation_result["warnings"]),
                "config_structure_valid": validation_result["validation_details"]["config_structure"]["valid"] if validation_result["validation_details"]["config_structure"] else False,
                "query_syntax_valid": validation_result["query_syntax_valid"],
                "trigger_conditions_valid": validation_result["trigger_conditions_valid"],
                "notifications_valid": validation_result["notifications_valid"]
            }
            
            logger.info(
                "Monitor configuration validation completed",
                extra={
                    "valid": validation_result["valid"],
                    "errors": len(validation_result["errors"]),
                    "warnings": len(validation_result["warnings"])
                }
            )
            
            return validation_result
            
        except Exception as e:
            logger.error(
                "Unexpected error during monitor configuration validation",
                extra={"error": str(e), "error_type": type(e).__name__}
            )
            raise APIError(
                f"Unexpected error during validation: {str(e)}",
                context={"operation": "validate_monitor_config"}
            ) from e
    
    def _validate_trigger_conditions(self, trigger_conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Validate trigger conditions configuration.
        
        Args:
            trigger_conditions: Dictionary of trigger conditions
            
        Returns:
            Dictionary containing validation results for trigger conditions
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "conditions_checked": []
        }
        
        if not trigger_conditions:
            result["valid"] = False
            result["errors"].append("At least one trigger condition must be specified")
            return result
        
        valid_trigger_types = [TriggerType.CRITICAL, TriggerType.WARNING, TriggerType.MISSING_DATA]
        
        for trigger_type, condition in trigger_conditions.items():
            condition_result = {
                "trigger_type": trigger_type,
                "valid": True,
                "errors": [],
                "warnings": []
            }
            
            # Validate trigger type
            if trigger_type not in [t.value for t in valid_trigger_types]:
                condition_result["valid"] = False
                condition_result["errors"].append(f"Invalid trigger type: {trigger_type}")
                result["valid"] = False
            
            # Validate condition structure
            if not isinstance(condition, dict):
                condition_result["valid"] = False
                condition_result["errors"].append("Trigger condition must be a dictionary")
                result["valid"] = False
            else:
                # Validate required fields
                required_fields = ["threshold", "threshold_type", "time_range"]
                for field in required_fields:
                    if field not in condition:
                        condition_result["valid"] = False
                        condition_result["errors"].append(f"Missing required field: {field}")
                        result["valid"] = False
                
                # Validate threshold
                threshold = condition.get("threshold")
                if threshold is not None:
                    try:
                        float(threshold)
                    except (ValueError, TypeError):
                        condition_result["valid"] = False
                        condition_result["errors"].append("Threshold must be a valid number")
                        result["valid"] = False
                
                # Validate threshold_type
                threshold_type = condition.get("threshold_type")
                valid_threshold_types = [t.value for t in ThresholdType]
                if threshold_type and threshold_type not in valid_threshold_types:
                    condition_result["valid"] = False
                    condition_result["errors"].append(
                        f"Invalid threshold_type: {threshold_type}. Must be one of: {', '.join(valid_threshold_types)}"
                    )
                    result["valid"] = False
                
                # Validate time_range format
                time_range = condition.get("time_range")
                if time_range:
                    import re
                    if not re.match(r'^-?\d+[smhdw]$', time_range):
                        condition_result["valid"] = False
                        condition_result["errors"].append(
                            f"Invalid time_range format: {time_range}. Must be like '-5m', '-1h', '-1d'"
                        )
                        result["valid"] = False
                
                # Add warnings for best practices
                if threshold is not None and threshold == 0:
                    condition_result["warnings"].append(
                        "Threshold of 0 may cause frequent triggering"
                    )
                
                if time_range and time_range.startswith('-') and int(time_range[1:-1]) > 60 and time_range.endswith('m'):
                    condition_result["warnings"].append(
                        "Time range longer than 60 minutes may cause delayed alerting"
                    )
            
            result["conditions_checked"].append(condition_result)
            result["errors"].extend(condition_result["errors"])
            result["warnings"].extend(condition_result["warnings"])
        
        return result
    
    def _validate_notification_configurations(self, notifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate notification configurations.
        
        Args:
            notifications: List of notification configuration dictionaries
            
        Returns:
            Dictionary containing validation results for notifications
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "notifications_checked": []
        }
        
        if not notifications:
            result["warnings"].append("No notifications configured - monitor will not send alerts")
            return result
        
        if not isinstance(notifications, list):
            result["valid"] = False
            result["errors"].append("Notifications must be a list")
            return result
        
        valid_action_types = [t.value for t in NotificationType]
        
        for i, notification in enumerate(notifications):
            notification_result = {
                "index": i,
                "valid": True,
                "errors": [],
                "warnings": []
            }
            
            if not isinstance(notification, dict):
                notification_result["valid"] = False
                notification_result["errors"].append("Notification must be a dictionary")
                result["valid"] = False
            else:
                # Validate action_type
                action_type = notification.get("action_type")
                if not action_type:
                    notification_result["valid"] = False
                    notification_result["errors"].append("action_type is required")
                    result["valid"] = False
                elif action_type not in valid_action_types:
                    notification_result["valid"] = False
                    notification_result["errors"].append(
                        f"Invalid action_type: {action_type}. Must be one of: {', '.join(valid_action_types)}"
                    )
                    result["valid"] = False
                
                # Validate type-specific requirements
                if action_type == NotificationType.EMAIL:
                    recipients = notification.get("recipients", [])
                    if not recipients:
                        notification_result["valid"] = False
                        notification_result["errors"].append("Email notifications require recipients")
                        result["valid"] = False
                    else:
                        # Validate email addresses
                        import re
                        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                        for email in recipients:
                            if not re.match(email_pattern, email):
                                notification_result["valid"] = False
                                notification_result["errors"].append(f"Invalid email address: {email}")
                                result["valid"] = False
                
                elif action_type == NotificationType.WEBHOOK:
                    webhook_url = notification.get("webhook_url")
                    if not webhook_url:
                        notification_result["valid"] = False
                        notification_result["errors"].append("Webhook notifications require webhook_url")
                        result["valid"] = False
                    elif not webhook_url.startswith(('http://', 'https://')):
                        notification_result["valid"] = False
                        notification_result["errors"].append("Webhook URL must start with http:// or https://")
                        result["valid"] = False
                
                # Validate optional fields
                subject = notification.get("subject")
                if subject and len(subject) > 255:
                    notification_result["warnings"].append("Subject is longer than 255 characters")
                
                message_body = notification.get("message_body")
                if message_body and len(message_body) > 2000:
                    notification_result["warnings"].append("Message body is longer than 2000 characters")
            
            result["notifications_checked"].append(notification_result)
            result["errors"].extend(notification_result["errors"])
            result["warnings"].extend(notification_result["warnings"])
        
        return result
    
    def _perform_additional_validation_checks(self, config: Dict[str, Any], validation_result: Dict[str, Any]) -> None:
        """Perform additional validation checks and add warnings.
        
        Args:
            config: Monitor configuration dictionary
            validation_result: Validation result dictionary to update
        """
        # Check for potential performance issues
        query = config.get("query", "")
        if query:
            # Warn about potentially expensive queries
            expensive_patterns = [
                r'\*\s*\|\s*count',  # * | count without filters
                r'_raw\s*matches',   # _raw matches (can be slow)
                r'join\s+',          # joins can be expensive
            ]
            
            import re
            for pattern in expensive_patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    validation_result["warnings"].append(
                        f"Query contains potentially expensive operation: {pattern}"
                    )
        
        # Check evaluation delay
        evaluation_delay = config.get("evaluation_delay", "0m")
        if evaluation_delay and evaluation_delay != "0m":
            import re
            if re.match(r'^\d+[smh]$', evaluation_delay):
                delay_match = re.match(r'^(\d+)([smh])$', evaluation_delay)
                if delay_match:
                    value, unit = delay_match.groups()
                    value = int(value)
                    
                    # Convert to minutes for comparison
                    if unit == 's':
                        delay_minutes = value / 60
                    elif unit == 'm':
                        delay_minutes = value
                    elif unit == 'h':
                        delay_minutes = value * 60
                    
                    if delay_minutes > 60:
                        validation_result["warnings"].append(
                            "Evaluation delay longer than 1 hour may significantly delay alerting"
                        )
        
        # Check for missing description
        if not config.get("description", "").strip():
            validation_result["warnings"].append(
                "Monitor description is empty - consider adding a description for better documentation"
            )
        
        # Check monitor name length and characters
        name = config.get("name", "")
        if len(name) > 200:
            validation_result["warnings"].append(
                "Monitor name is very long - consider using a shorter, more concise name"
            )
        
        # Check if monitor is disabled by default
        if config.get("is_disabled", False):
            validation_result["warnings"].append(
                "Monitor is configured as disabled - it will not evaluate until enabled"
            )

    async def get_monitor_history(
        self,
        monitor_id: str,
        from_time: str,
        to_time: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get monitor execution history with comprehensive error handling.
        
        This method retrieves the execution history for a specific monitor,
        including performance metrics, execution statistics, and trigger patterns
        over the specified time range.
        
        Args:
            monitor_id: Unique identifier for the monitor
            from_time: Start time for history range (ISO format or relative like '-1h')
            to_time: End time for history range (ISO format or relative like 'now')
            limit: Maximum number of history entries to return (1-1000)
            
        Returns:
            Dictionary containing monitor execution history with:
            - execution_history: List of execution entries with timestamps and results
            - performance_metrics: Aggregated performance statistics
            - trigger_patterns: Analysis of trigger frequency and patterns
            - metadata: Request metadata and pagination info
            
        Raises:
            MonitorValidationError: If parameters are invalid
            MonitorNotFoundError: If monitor doesn't exist
            MonitorError: If history retrieval fails
            RateLimitError: If rate limit is exceeded
        """
        async def _get_monitor_history_impl():
            # Validate monitor_id
            validated_monitor_id = await validate_monitor_id(monitor_id, "get_monitor_history")
            
            # Validate time parameters
            if not from_time or not isinstance(from_time, str):
                raise MonitorValidationError(
                    "from_time must be a non-empty string",
                    field_name="from_time",
                    field_value=from_time,
                    context=create_monitor_error_context(
                        "get_monitor_history",
                        monitor_id=validated_monitor_id
                    )
                )
            
            if not to_time or not isinstance(to_time, str):
                raise MonitorValidationError(
                    "to_time must be a non-empty string",
                    field_name="to_time",
                    field_value=to_time,
                    context=create_monitor_error_context(
                        "get_monitor_history",
                        monitor_id=validated_monitor_id
                    )
                )
            
            # Validate limit parameter
            if not isinstance(limit, int) or limit < 1 or limit > 1000:
                raise MonitorValidationError(
                    "Limit must be an integer between 1 and 1000",
                    field_name="limit",
                    field_value=limit,
                    context=create_monitor_error_context(
                        "get_monitor_history",
                        monitor_id=validated_monitor_id
                    )
                )
            
            # Get monitor history from API with error handling
            try:
                api_response = await self.api_client.get_monitor_history(
                    monitor_id=validated_monitor_id,
                    from_time=from_time,
                    to_time=to_time,
                    limit=limit
                )
            except RateLimitError as e:
                raise RateLimitError(
                    f"Rate limit exceeded while getting monitor history: {e.message}",
                    retry_after=e.retry_after,
                    limit_type=e.limit_type,
                    context=create_monitor_error_context(
                        "get_monitor_history",
                        monitor_id=validated_monitor_id,
                        time_range=f"{from_time} to {to_time}"
                    )
                ) from e
            
            # Extract history data from response
            history_data = api_response.get("data", [])
            total_count = api_response.get("total", len(history_data))
            
            # Handle case with no history data
            if not history_data:
                return {
                    "success": True,
                    "execution_history": [],
                    "performance_metrics": {
                        "total_executions": 0,
                        "average_execution_time": 0,
                        "success_rate": 0,
                        "trigger_rate": 0
                    },
                    "trigger_patterns": {
                        "total_triggers": 0,
                        "trigger_frequency": {},
                        "severity_distribution": {}
                    },
                    "metadata": {
                        "monitor_id": validated_monitor_id,
                        "time_range": {"from": from_time, "to": to_time},
                        "total_entries": 0,
                        "returned_entries": 0,
                        "limit": limit,
                        "retrieved_at": datetime.now().isoformat()
                    },
                    "message": "No execution history found for the specified time range"
                }
            
            # Format execution history with error handling
            formatted_history = []
            formatting_errors = []
            
            for i, entry in enumerate(history_data):
                try:
                    formatted_entry = self._format_history_entry(entry)
                    formatted_history.append(formatted_entry)
                except Exception as e:
                    formatting_errors.append({
                        "index": i,
                        "entry_id": entry.get("executionId", "unknown"),
                        "error": str(e)
                    })
                    logger.warning(
                        f"Failed to format history entry {entry.get('executionId', 'unknown')}: {str(e)}",
                        extra={"entry": entry, "error": str(e)}
                    )
                    # Continue with other entries
                    continue
            
            if not formatted_history and formatting_errors:
                raise MonitorError(
                    f"Failed to format any history entries: {len(formatting_errors)} formatting errors",
                    monitor_id=validated_monitor_id,
                    operation="get_monitor_history",
                    context=create_monitor_error_context(
                        "get_monitor_history",
                        monitor_id=validated_monitor_id,
                        formatting_errors=formatting_errors,
                        total_entries=len(history_data)
                    )
                )
            
            # Calculate performance metrics
            try:
                performance_metrics = self._calculate_performance_metrics(formatted_history)
            except Exception as e:
                logger.warning(
                    f"Failed to calculate performance metrics: {str(e)}",
                    extra={"monitor_id": validated_monitor_id, "history_count": len(formatted_history)}
                )
                performance_metrics = {
                    "total_executions": len(formatted_history),
                    "calculation_error": str(e)
                }
            
            # Analyze trigger patterns
            try:
                trigger_patterns = self._analyze_trigger_patterns(formatted_history)
            except Exception as e:
                logger.warning(
                    f"Failed to analyze trigger patterns: {str(e)}",
                    extra={"monitor_id": validated_monitor_id, "history_count": len(formatted_history)}
                )
                trigger_patterns = {
                    "analysis_error": str(e)
                }
            
            response = {
                "success": True,
                "execution_history": formatted_history,
                "performance_metrics": performance_metrics,
                "trigger_patterns": trigger_patterns,
                "metadata": {
                    "monitor_id": validated_monitor_id,
                    "time_range": {"from": from_time, "to": to_time},
                    "total_entries": total_count,
                    "returned_entries": len(formatted_history),
                    "limit": limit,
                    "retrieved_at": datetime.now().isoformat()
                }
            }
            
            # Add formatting warnings if any
            if formatting_errors:
                response["warnings"] = {
                    "formatting_errors": len(formatting_errors),
                    "message": f"{len(formatting_errors)} history entries could not be formatted and were skipped"
                }
            
            return response
        
        # Execute with comprehensive error handling
        return await self.error_handler.execute_with_error_handling(
            "get_monitor_history",
            _get_monitor_history_impl,
            monitor_id=monitor_id,
            timeout_override=60.0  # History operations may take longer
        )
        logger.info(
            "Getting monitor execution history",
            extra={
                "monitor_id": monitor_id,
                "from_time": from_time,
                "to_time": to_time,
                "limit": limit
            }
        )
        
        # Validate parameters
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
        
        try:
            # Get monitor history from API
            api_response = await self.api_client.get_monitor_history(
                monitor_id=monitor_id,
                from_time=from_time,
                to_time=to_time,
                limit=limit
            )
            
            # Extract history data from API response
            history_data = api_response.get("data", [])
            
            # Process and format history entries
            formatted_history = self._format_history_entries(history_data)
            
            # Calculate performance metrics
            performance_metrics = self._calculate_performance_metrics(history_data)
            
            # Analyze trigger patterns
            trigger_patterns = self._analyze_trigger_patterns(history_data)
            
            # Format response with comprehensive information
            response = {
                "success": True,
                "monitor_id": monitor_id,
                "execution_history": formatted_history,
                "performance_metrics": performance_metrics,
                "trigger_patterns": trigger_patterns,
                "metadata": {
                    "time_range": {
                        "from": from_time,
                        "to": to_time
                    },
                    "total_entries": len(formatted_history),
                    "limit": limit,
                    "has_more": len(history_data) >= limit,
                    "generated_at": datetime.utcnow().isoformat() + "Z"
                }
            }
            
            logger.info(
                "Successfully retrieved monitor execution history",
                extra={
                    "monitor_id": monitor_id,
                    "entries_returned": len(formatted_history),
                    "triggers_found": len([h for h in formatted_history if h.get("triggered", False)])
                }
            )
            
            return response
            
        except APIError as e:
            logger.error(
                "Failed to get monitor history",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "status_code": getattr(e, 'status_code', None)
                }
            )
            
            # Provide more specific error messages
            if hasattr(e, 'status_code'):
                if e.status_code == 404:
                    raise APIError(
                        f"Monitor not found: {monitor_id}. Please verify the monitor ID is correct.",
                        status_code=404,
                        request_id=getattr(e, 'request_id', None),
                        context={
                            "operation": "get_monitor_history",
                            "monitor_id": monitor_id
                        }
                    ) from e
                elif e.status_code == 403:
                    raise APIError(
                        f"Insufficient permissions to access monitor history for monitor: {monitor_id}",
                        status_code=403,
                        request_id=getattr(e, 'request_id', None),
                        context={
                            "operation": "get_monitor_history",
                            "monitor_id": monitor_id
                        }
                    ) from e
            
            raise APIError(
                f"Failed to get monitor history: {e.message}",
                status_code=getattr(e, 'status_code', None),
                request_id=getattr(e, 'request_id', None),
                context={
                    "operation": "get_monitor_history",
                    "monitor_id": monitor_id,
                    "from_time": from_time,
                    "to_time": to_time
                }
            ) from e
        
        except Exception as e:
            logger.error(
                "Unexpected error getting monitor history",
                extra={
                    "monitor_id": monitor_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise APIError(
                f"Unexpected error getting monitor history: {str(e)}",
                context={
                    "operation": "get_monitor_history",
                    "monitor_id": monitor_id
                }
            ) from e

    def _format_history_entries(self, history_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format raw history data into structured execution entries.
        
        Args:
            history_data: Raw history data from API
            
        Returns:
            List of formatted history entries with execution details
        """
        formatted_entries = []
        
        for entry in history_data:
            try:
                # Extract and format execution information
                formatted_entry = {
                    "timestamp": entry.get("timestamp", ""),
                    "status": entry.get("status", "unknown"),
                    "execution_duration_ms": entry.get("executionDurationMs"),
                    "result_count": entry.get("resultCount"),
                    "triggered": entry.get("triggered", False),
                    "trigger_value": entry.get("triggerValue"),
                    "trigger_severity": entry.get("triggerSeverity"),
                    "error_message": entry.get("errorMessage"),
                    "query_execution_time_ms": entry.get("queryExecutionTimeMs"),
                    "data_scanned_bytes": entry.get("dataScannedBytes"),
                    "evaluation_result": entry.get("evaluationResult", {})
                }
                
                # Add trigger details if monitor was triggered
                if formatted_entry["triggered"]:
                    formatted_entry["trigger_details"] = {
                        "severity": entry.get("triggerSeverity", "Unknown"),
                        "threshold_exceeded": entry.get("thresholdExceeded"),
                        "trigger_condition": entry.get("triggerCondition", {}),
                        "alert_sent": entry.get("alertSent", False)
                    }
                
                # Add performance indicators
                formatted_entry["performance_indicators"] = {
                    "execution_fast": (entry.get("executionDurationMs", 0) < 5000),  # < 5 seconds
                    "data_volume_normal": (entry.get("dataScannedBytes", 0) < 100 * 1024 * 1024),  # < 100MB
                    "result_count_reasonable": (entry.get("resultCount", 0) < 10000)  # < 10k results
                }
                
                formatted_entries.append(formatted_entry)
                
            except Exception as e:
                logger.warning(
                    f"Failed to format history entry: {str(e)}",
                    extra={"entry": entry}
                )
                # Include raw entry with error marker
                formatted_entries.append({
                    "timestamp": entry.get("timestamp", ""),
                    "status": "format_error",
                    "error_message": f"Failed to format entry: {str(e)}",
                    "raw_entry": entry
                })
        
        # Sort by timestamp (most recent first)
        formatted_entries.sort(
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )
        
        return formatted_entries

    def _calculate_performance_metrics(self, history_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate aggregated performance metrics from history data.
        
        Args:
            history_data: Raw history data from API
            
        Returns:
            Dictionary containing performance statistics and metrics
        """
        if not history_data:
            return {
                "total_executions": 0,
                "avg_execution_time_ms": 0,
                "max_execution_time_ms": 0,
                "min_execution_time_ms": 0,
                "success_rate": 0.0,
                "error_rate": 0.0,
                "avg_result_count": 0,
                "total_data_scanned_bytes": 0,
                "avg_data_scanned_bytes": 0
            }
        
        # Extract metrics from history entries
        execution_times = []
        result_counts = []
        data_scanned = []
        successful_executions = 0
        failed_executions = 0
        
        for entry in history_data:
            # Execution time metrics
            exec_time = entry.get("executionDurationMs")
            if exec_time is not None and isinstance(exec_time, (int, float)):
                execution_times.append(exec_time)
            
            # Result count metrics
            result_count = entry.get("resultCount")
            if result_count is not None and isinstance(result_count, (int, float)):
                result_counts.append(result_count)
            
            # Data scanned metrics
            data_bytes = entry.get("dataScannedBytes")
            if data_bytes is not None and isinstance(data_bytes, (int, float)):
                data_scanned.append(data_bytes)
            
            # Success/failure tracking
            status = entry.get("status", "").lower()
            if status in ["success", "completed", "normal"]:
                successful_executions += 1
            elif status in ["error", "failed", "timeout"]:
                failed_executions += 1
        
        total_executions = len(history_data)
        
        # Calculate aggregated metrics
        metrics = {
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "failed_executions": failed_executions,
            "success_rate": (successful_executions / total_executions * 100) if total_executions > 0 else 0.0,
            "error_rate": (failed_executions / total_executions * 100) if total_executions > 0 else 0.0
        }
        
        # Execution time statistics
        if execution_times:
            metrics.update({
                "avg_execution_time_ms": sum(execution_times) / len(execution_times),
                "max_execution_time_ms": max(execution_times),
                "min_execution_time_ms": min(execution_times),
                "median_execution_time_ms": sorted(execution_times)[len(execution_times) // 2]
            })
        else:
            metrics.update({
                "avg_execution_time_ms": 0,
                "max_execution_time_ms": 0,
                "min_execution_time_ms": 0,
                "median_execution_time_ms": 0
            })
        
        # Result count statistics
        if result_counts:
            metrics.update({
                "avg_result_count": sum(result_counts) / len(result_counts),
                "max_result_count": max(result_counts),
                "min_result_count": min(result_counts),
                "total_results_processed": sum(result_counts)
            })
        else:
            metrics.update({
                "avg_result_count": 0,
                "max_result_count": 0,
                "min_result_count": 0,
                "total_results_processed": 0
            })
        
        # Data scanning statistics
        if data_scanned:
            total_data = sum(data_scanned)
            metrics.update({
                "total_data_scanned_bytes": total_data,
                "avg_data_scanned_bytes": total_data / len(data_scanned),
                "max_data_scanned_bytes": max(data_scanned),
                "min_data_scanned_bytes": min(data_scanned),
                "total_data_scanned_mb": round(total_data / (1024 * 1024), 2),
                "avg_data_scanned_mb": round((total_data / len(data_scanned)) / (1024 * 1024), 2)
            })
        else:
            metrics.update({
                "total_data_scanned_bytes": 0,
                "avg_data_scanned_bytes": 0,
                "max_data_scanned_bytes": 0,
                "min_data_scanned_bytes": 0,
                "total_data_scanned_mb": 0,
                "avg_data_scanned_mb": 0
            })
        
        # Performance indicators
        metrics["performance_indicators"] = {
            "fast_execution_rate": len([t for t in execution_times if t < 5000]) / len(execution_times) * 100 if execution_times else 0,
            "slow_execution_count": len([t for t in execution_times if t > 30000]),  # > 30 seconds
            "high_data_volume_count": len([d for d in data_scanned if d > 100 * 1024 * 1024]),  # > 100MB
            "large_result_set_count": len([r for r in result_counts if r > 10000])  # > 10k results
        }
        
        return metrics

    def _analyze_trigger_patterns(self, history_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trigger patterns and frequency from history data.
        
        Args:
            history_data: Raw history data from API
            
        Returns:
            Dictionary containing trigger pattern analysis and statistics
        """
        if not history_data:
            return {
                "total_triggers": 0,
                "trigger_rate": 0.0,
                "triggers_by_severity": {},
                "trigger_frequency": {},
                "recent_trigger_trend": "stable"
            }
        
        # Extract trigger information
        triggers = []
        triggers_by_severity = {}
        trigger_timestamps = []
        
        for entry in history_data:
            if entry.get("triggered", False):
                trigger_info = {
                    "timestamp": entry.get("timestamp", ""),
                    "severity": entry.get("triggerSeverity", "Unknown"),
                    "trigger_value": entry.get("triggerValue"),
                    "threshold_exceeded": entry.get("thresholdExceeded")
                }
                triggers.append(trigger_info)
                trigger_timestamps.append(entry.get("timestamp", ""))
                
                # Count by severity
                severity = trigger_info["severity"]
                triggers_by_severity[severity] = triggers_by_severity.get(severity, 0) + 1
        
        total_executions = len(history_data)
        total_triggers = len(triggers)
        
        # Calculate trigger rate
        trigger_rate = (total_triggers / total_executions * 100) if total_executions > 0 else 0.0
        
        # Analyze trigger frequency patterns
        trigger_frequency = self._calculate_trigger_frequency(trigger_timestamps)
        
        # Analyze recent trend
        recent_trend = self._analyze_recent_trigger_trend(history_data)
        
        # Calculate trigger duration patterns (if available)
        trigger_durations = self._analyze_trigger_durations(triggers)
        
        analysis = {
            "total_triggers": total_triggers,
            "trigger_rate": round(trigger_rate, 2),
            "triggers_by_severity": triggers_by_severity,
            "trigger_frequency": trigger_frequency,
            "recent_trigger_trend": recent_trend,
            "trigger_durations": trigger_durations,
            "trigger_details": triggers[:10],  # Include up to 10 most recent triggers
            "analysis_summary": {
                "is_frequently_triggering": trigger_rate > 10.0,  # > 10% trigger rate
                "has_critical_triggers": "Critical" in triggers_by_severity,
                "severity_distribution": {
                    severity: round(count / total_triggers * 100, 1) if total_triggers > 0 else 0
                    for severity, count in triggers_by_severity.items()
                }
            }
        }
        
        return analysis

    def _calculate_trigger_frequency(self, trigger_timestamps: List[str]) -> Dict[str, Any]:
        """Calculate trigger frequency patterns from timestamps.
        
        Args:
            trigger_timestamps: List of trigger timestamp strings
            
        Returns:
            Dictionary containing frequency analysis
        """
        if not trigger_timestamps:
            return {
                "triggers_per_hour": 0,
                "triggers_per_day": 0,
                "peak_trigger_hours": [],
                "trigger_intervals": []
            }
        
        from datetime import datetime
        import re
        
        # Parse timestamps and calculate intervals
        parsed_timestamps = []
        for ts in trigger_timestamps:
            try:
                # Handle different timestamp formats
                if ts.endswith('Z'):
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(ts)
                parsed_timestamps.append(dt)
            except ValueError:
                continue
        
        if len(parsed_timestamps) < 2:
            return {
                "triggers_per_hour": len(parsed_timestamps),
                "triggers_per_day": len(parsed_timestamps),
                "peak_trigger_hours": [],
                "trigger_intervals": []
            }
        
        # Sort timestamps
        parsed_timestamps.sort()
        
        # Calculate time span
        time_span = parsed_timestamps[-1] - parsed_timestamps[0]
        total_hours = time_span.total_seconds() / 3600
        total_days = time_span.days + (time_span.seconds / 86400)
        
        # Calculate frequency rates
        triggers_per_hour = len(parsed_timestamps) / total_hours if total_hours > 0 else 0
        triggers_per_day = len(parsed_timestamps) / total_days if total_days > 0 else 0
        
        # Analyze peak hours
        hour_counts = {}
        for dt in parsed_timestamps:
            hour = dt.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        # Find peak hours (hours with above-average trigger counts)
        avg_triggers_per_hour = len(parsed_timestamps) / 24 if len(parsed_timestamps) > 24 else 0
        peak_hours = [hour for hour, count in hour_counts.items() if count > avg_triggers_per_hour]
        
        # Calculate intervals between triggers
        intervals = []
        for i in range(1, len(parsed_timestamps)):
            interval = (parsed_timestamps[i] - parsed_timestamps[i-1]).total_seconds() / 60  # minutes
            intervals.append(interval)
        
        return {
            "triggers_per_hour": round(triggers_per_hour, 2),
            "triggers_per_day": round(triggers_per_day, 2),
            "peak_trigger_hours": sorted(peak_hours),
            "trigger_intervals": {
                "avg_interval_minutes": round(sum(intervals) / len(intervals), 2) if intervals else 0,
                "min_interval_minutes": round(min(intervals), 2) if intervals else 0,
                "max_interval_minutes": round(max(intervals), 2) if intervals else 0
            }
        }

    def _analyze_recent_trigger_trend(self, history_data: List[Dict[str, Any]]) -> str:
        """Analyze recent trigger trend to determine if triggers are increasing, decreasing, or stable.
        
        Args:
            history_data: Raw history data from API
            
        Returns:
            String indicating trend: "increasing", "decreasing", "stable", or "insufficient_data"
        """
        if len(history_data) < 10:
            return "insufficient_data"
        
        # Sort by timestamp (most recent first)
        sorted_data = sorted(
            history_data,
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )
        
        # Split into recent and older halves
        mid_point = len(sorted_data) // 2
        recent_half = sorted_data[:mid_point]
        older_half = sorted_data[mid_point:]
        
        # Count triggers in each half
        recent_triggers = sum(1 for entry in recent_half if entry.get("triggered", False))
        older_triggers = sum(1 for entry in older_half if entry.get("triggered", False))
        
        # Calculate trigger rates
        recent_rate = recent_triggers / len(recent_half) if recent_half else 0
        older_rate = older_triggers / len(older_half) if older_half else 0
        
        # Determine trend with threshold for significance
        threshold = 0.05  # 5% difference threshold
        
        if recent_rate > older_rate + threshold:
            return "increasing"
        elif recent_rate < older_rate - threshold:
            return "decreasing"
        else:
            return "stable"

    def _analyze_trigger_durations(self, triggers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trigger duration patterns if duration data is available.
        
        Args:
            triggers: List of trigger information dictionaries
            
        Returns:
            Dictionary containing trigger duration analysis
        """
        # This is a placeholder for trigger duration analysis
        # In a real implementation, this would analyze how long triggers last
        # based on when they start and when they resolve
        
        return {
            "avg_duration_minutes": 0,
            "max_duration_minutes": 0,
            "min_duration_minutes": 0,
            "unresolved_triggers": 0,
            "note": "Trigger duration analysis requires additional API data not available in execution history"
        }    

    # Additional error handling and utility methods
    
    async def handle_monitor_operation_error(
        self,
        error: Exception,
        operation: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Exception:
        """Handle and enhance monitor operation errors with context.
        
        This method provides a centralized way to handle and enhance errors
        from monitor operations, adding appropriate context and converting
        to monitor-specific error types.
        
        Args:
            error: Original exception
            operation: Monitor operation that failed
            monitor_id: Optional monitor ID
            monitor_name: Optional monitor name
            additional_context: Additional error context
            
        Returns:
            Enhanced exception with monitor context
        """
        context = create_monitor_error_context(
            operation,
            monitor_id=monitor_id,
            monitor_name=monitor_name
        )
        
        if additional_context:
            context.update(additional_context)
        
        # Use the error handler to enhance the error
        return await self.error_handler._enhance_error(
            error, operation, monitor_id, monitor_name, 0.0
        )
    
    async def validate_monitor_operation_preconditions(
        self,
        operation: str,
        monitor_id: Optional[str] = None,
        **operation_params
    ) -> Dict[str, Any]:
        """Validate preconditions for monitor operations.
        
        This method performs common validation checks before executing
        monitor operations to catch issues early and provide better
        error messages.
        
        Args:
            operation: Monitor operation to validate
            monitor_id: Optional monitor ID to validate
            **operation_params: Operation-specific parameters to validate
            
        Returns:
            Dictionary with validation results
            
        Raises:
            MonitorValidationError: If validation fails
        """
        validation_results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "validated_params": {}
        }
        
        # Validate monitor_id if provided
        if monitor_id is not None:
            try:
                validated_id = await validate_monitor_id(monitor_id, operation)
                validation_results["validated_params"]["monitor_id"] = validated_id
            except MonitorValidationError as e:
                validation_results["valid"] = False
                validation_results["errors"].append(str(e))
        
        # Operation-specific validations
        if operation in ["list_monitors", "search_monitors"]:
            # Validate pagination parameters
            limit = operation_params.get("limit", 100)
            offset = operation_params.get("offset", 0)
            try:
                validated_limit, validated_offset = await validate_pagination_params(
                    limit, offset, operation
                )
                validation_results["validated_params"]["limit"] = validated_limit
                validation_results["validated_params"]["offset"] = validated_offset
            except MonitorValidationError as e:
                validation_results["valid"] = False
                validation_results["errors"].append(str(e))
        
        elif operation == "create_monitor":
            # Validate required parameters for monitor creation
            name = operation_params.get("name")
            query = operation_params.get("query")
            trigger_conditions = operation_params.get("trigger_conditions")
            
            if not name or not name.strip():
                validation_results["valid"] = False
                validation_results["errors"].append("Monitor name is required")
            elif len(name.strip()) > 255:
                validation_results["valid"] = False
                validation_results["errors"].append("Monitor name cannot exceed 255 characters")
            
            if not query or not query.strip():
                validation_results["valid"] = False
                validation_results["errors"].append("Monitor query is required")
            
            if not trigger_conditions:
                validation_results["valid"] = False
                validation_results["errors"].append("Trigger conditions are required")
        
        # Add warnings for potentially problematic configurations
        if operation == "delete_monitor" and monitor_id:
            validation_results["warnings"].append(
                "Monitor deletion is irreversible. Ensure you have backups if needed."
            )
        
        return validation_results
    
    def log_monitor_operation_metrics(
        self,
        operation: str,
        success: bool,
        execution_time_ms: float,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        error_type: Optional[str] = None
    ):
        """Log monitor operation metrics for monitoring and analysis.
        
        Args:
            operation: Monitor operation name
            success: Whether the operation was successful
            execution_time_ms: Execution time in milliseconds
            monitor_id: Optional monitor ID
            monitor_name: Optional monitor name
            error_type: Optional error type if operation failed
        """
        log_context = {
            "operation": operation,
            "success": success,
            "execution_time_ms": round(execution_time_ms, 2),
            "tool": "monitor_tools"
        }
        
        if monitor_id:
            log_context["monitor_id"] = monitor_id
        if monitor_name:
            log_context["monitor_name"] = monitor_name
        if error_type:
            log_context["error_type"] = error_type
        
        if success:
            logger.info("Monitor operation completed successfully", extra=log_context)
        else:
            logger.error("Monitor operation failed", extra=log_context)
    
    async def get_monitor_operation_health(self) -> Dict[str, Any]:
        """Get health status of monitor operations and error handling.
        
        Returns:
            Dictionary containing health status and operational metrics
        """
        error_stats = self.get_error_statistics()
        
        # Determine overall health based on error patterns
        health_status = "healthy"
        health_issues = []
        
        # Check circuit breaker status
        circuit_status = error_stats["resilience_status"]["circuit_breaker"]["state"]
        if circuit_status == "open":
            health_status = "unhealthy"
            health_issues.append("Circuit breaker is open")
        elif circuit_status == "half_open":
            health_status = "degraded"
            health_issues.append("Circuit breaker is in recovery mode")
        
        # Check error rates
        recent_errors = error_stats["monitor_tools_errors"]["recent_errors"]
        if len(recent_errors) > 10:
            health_status = "degraded"
            health_issues.append(f"High recent error count: {len(recent_errors)}")
        
        # Check for specific error patterns
        error_patterns = error_stats["monitor_tools_errors"]["error_patterns"]
        for error_key, count in error_patterns.items():
            if count > 5:
                if health_status == "healthy":
                    health_status = "degraded"
                health_issues.append(f"High error count for {error_key}: {count}")
        
        return {
            "health_status": health_status,
            "health_issues": health_issues,
            "error_statistics": error_stats,
            "recommendations": self._generate_health_recommendations(health_status, health_issues),
            "last_check": datetime.now().isoformat()
        }
    
    def _generate_health_recommendations(
        self, 
        health_status: str, 
        health_issues: List[str]
    ) -> List[str]:
        """Generate health recommendations based on current status.
        
        Args:
            health_status: Current health status
            health_issues: List of identified health issues
            
        Returns:
            List of recommendations to improve health
        """
        recommendations = []
        
        if health_status == "unhealthy":
            recommendations.append("Check Sumo Logic API connectivity and authentication")
            recommendations.append("Verify network connectivity and firewall settings")
            recommendations.append("Consider increasing timeout values if operations are timing out")
        
        elif health_status == "degraded":
            recommendations.append("Monitor error patterns and consider adjusting retry policies")
            recommendations.append("Check for rate limiting and adjust request frequency if needed")
            recommendations.append("Verify monitor configurations are valid")
        
        # Specific recommendations based on issues
        for issue in health_issues:
            if "circuit breaker" in issue.lower():
                recommendations.append("Wait for circuit breaker recovery or check underlying service health")
            elif "error count" in issue.lower():
                recommendations.append("Investigate specific error patterns and root causes")
            elif "rate limit" in issue.lower():
                recommendations.append("Reduce request frequency or implement better rate limiting")
        
        if not recommendations:
            recommendations.append("Monitor operations are healthy - continue normal operations")
        
        return recommendations   
 
    # Enhanced logging and monitoring methods
    
    def configure_enhanced_logging(self, log_level: str = "INFO", enable_structured_logging: bool = True):
        """Configure enhanced logging for monitor operations.
        
        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            enable_structured_logging: Whether to enable structured logging with extra context
        """
        # Configure the logger for this module
        monitor_logger = logging.getLogger(__name__)
        monitor_logger.setLevel(getattr(logging, log_level.upper()))
        
        # Create formatter for structured logging
        if enable_structured_logging:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(extra_context)s',
                defaults={'extra_context': '{}'}
            )
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        
        # Add console handler if not already present
        if not monitor_logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            monitor_logger.addHandler(console_handler)
        
        logger.info(
            "Enhanced logging configured for monitor tools",
            extra={
                "log_level": log_level,
                "structured_logging": enable_structured_logging,
                "logger_name": __name__
            }
        )
    
    async def log_monitor_operation_start(
        self,
        operation: str,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        **operation_params
    ):
        """Log the start of a monitor operation with context.
        
        Args:
            operation: Monitor operation name
            monitor_id: Optional monitor ID
            monitor_name: Optional monitor name
            **operation_params: Additional operation parameters to log
        """
        log_context = {
            "operation": operation,
            "operation_stage": "start",
            "timestamp": datetime.now().isoformat()
        }
        
        if monitor_id:
            log_context["monitor_id"] = monitor_id
        if monitor_name:
            log_context["monitor_name"] = monitor_name
        
        # Add operation-specific parameters (sanitized)
        if operation_params:
            sanitized_params = self._sanitize_log_parameters(operation_params)
            log_context["operation_params"] = sanitized_params
        
        logger.info(f"Starting monitor operation: {operation}", extra=log_context)
    
    async def log_monitor_operation_success(
        self,
        operation: str,
        execution_time_ms: float,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        result_summary: Optional[Dict[str, Any]] = None
    ):
        """Log successful completion of a monitor operation.
        
        Args:
            operation: Monitor operation name
            execution_time_ms: Execution time in milliseconds
            monitor_id: Optional monitor ID
            monitor_name: Optional monitor name
            result_summary: Optional summary of operation results
        """
        log_context = {
            "operation": operation,
            "operation_stage": "success",
            "execution_time_ms": round(execution_time_ms, 2),
            "timestamp": datetime.now().isoformat()
        }
        
        if monitor_id:
            log_context["monitor_id"] = monitor_id
        if monitor_name:
            log_context["monitor_name"] = monitor_name
        if result_summary:
            log_context["result_summary"] = result_summary
        
        logger.info(f"Monitor operation completed successfully: {operation}", extra=log_context)
    
    async def log_monitor_operation_error(
        self,
        operation: str,
        error: Exception,
        execution_time_ms: float,
        monitor_id: Optional[str] = None,
        monitor_name: Optional[str] = None,
        error_context: Optional[Dict[str, Any]] = None
    ):
        """Log failed monitor operation with error details.
        
        Args:
            operation: Monitor operation name
            error: Exception that occurred
            execution_time_ms: Execution time in milliseconds
            monitor_id: Optional monitor ID
            monitor_name: Optional monitor name
            error_context: Optional additional error context
        """
        log_context = {
            "operation": operation,
            "operation_stage": "error",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "execution_time_ms": round(execution_time_ms, 2),
            "timestamp": datetime.now().isoformat()
        }
        
        if monitor_id:
            log_context["monitor_id"] = monitor_id
        if monitor_name:
            log_context["monitor_name"] = monitor_name
        if error_context:
            log_context["error_context"] = error_context
        
        # Add specific error details based on error type
        if isinstance(error, MonitorError):
            log_context["monitor_error_details"] = {
                "monitor_id": error.monitor_id,
                "monitor_name": error.monitor_name,
                "operation": error.operation,
                "context": error.context
            }
        elif isinstance(error, APIError):
            log_context["api_error_details"] = {
                "status_code": error.status_code,
                "request_id": error.request_id,
                "is_retryable": error.is_retryable
            }
        elif isinstance(error, RateLimitError):
            log_context["rate_limit_details"] = {
                "retry_after": error.retry_after,
                "limit_type": error.limit_type
            }
        
        logger.error(f"Monitor operation failed: {operation}", extra=log_context)
    
    def _sanitize_log_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize parameters for logging to remove sensitive information.
        
        Args:
            params: Parameters dictionary to sanitize
            
        Returns:
            Sanitized parameters dictionary
        """
        sanitized = {}
        sensitive_keys = {
            'password', 'token', 'key', 'secret', 'credential', 'auth',
            'webhook_url', 'api_key', 'access_token', 'private_key'
        }
        
        for key, value in params.items():
            key_lower = key.lower()
            
            # Check if key contains sensitive information
            if any(sensitive_word in key_lower for sensitive_word in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, str) and len(value) > 100:
                # Truncate very long strings
                sanitized[key] = value[:100] + "... [TRUNCATED]"
            elif isinstance(value, dict):
                # Recursively sanitize nested dictionaries
                sanitized[key] = self._sanitize_log_parameters(value)
            elif isinstance(value, list) and len(value) > 10:
                # Limit list size in logs
                sanitized[key] = value[:10] + ["... [TRUNCATED]"]
            else:
                sanitized[key] = value
        
        return sanitized
    
    async def generate_monitor_operation_report(
        self,
        time_range_hours: int = 24
    ) -> Dict[str, Any]:
        """Generate a comprehensive report of monitor operations.
        
        Args:
            time_range_hours: Time range in hours for the report
            
        Returns:
            Dictionary containing operation report with statistics and insights
        """
        try:
            # Get error statistics
            error_stats = self.get_error_statistics()
            
            # Get health status
            health_status = await self.get_monitor_operation_health()
            
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=time_range_hours)
            
            report = {
                "report_metadata": {
                    "generated_at": end_time.isoformat(),
                    "time_range": {
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat(),
                        "duration_hours": time_range_hours
                    },
                    "report_version": "1.0"
                },
                "error_statistics": error_stats,
                "health_status": health_status,
                "operational_insights": self._generate_operational_insights(error_stats, health_status),
                "recommendations": self._generate_operational_recommendations(error_stats, health_status)
            }
            
            logger.info(
                "Generated monitor operation report",
                extra={
                    "time_range_hours": time_range_hours,
                    "health_status": health_status["health_status"],
                    "total_error_types": error_stats["monitor_tools_errors"]["total_error_types"]
                }
            )
            
            return report
            
        except Exception as e:
            logger.error(
                f"Failed to generate monitor operation report: {str(e)}",
                extra={"error": str(e), "time_range_hours": time_range_hours}
            )
            return {
                "report_metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "generation_error": str(e)
                },
                "error": f"Report generation failed: {str(e)}"
            }
    
    def _generate_operational_insights(
        self,
        error_stats: Dict[str, Any],
        health_status: Dict[str, Any]
    ) -> List[str]:
        """Generate operational insights from error statistics and health status.
        
        Args:
            error_stats: Error statistics dictionary
            health_status: Health status dictionary
            
        Returns:
            List of operational insights
        """
        insights = []
        
        # Analyze error patterns
        monitor_errors = error_stats.get("monitor_tools_errors", {})
        total_errors = monitor_errors.get("total_errors", 0)
        error_patterns = monitor_errors.get("error_patterns", {})
        
        if total_errors == 0:
            insights.append("No errors detected in monitor operations - system is operating normally")
        elif total_errors < 5:
            insights.append(f"Low error rate detected ({total_errors} total errors) - system is stable")
        elif total_errors < 20:
            insights.append(f"Moderate error rate detected ({total_errors} total errors) - monitor for trends")
        else:
            insights.append(f"High error rate detected ({total_errors} total errors) - investigation recommended")
        
        # Analyze circuit breaker status
        circuit_status = error_stats.get("resilience_status", {}).get("circuit_breaker", {}).get("state")
        if circuit_status == "open":
            insights.append("Circuit breaker is open - service may be experiencing persistent failures")
        elif circuit_status == "half_open":
            insights.append("Circuit breaker is in recovery mode - monitoring service recovery")
        
        # Analyze specific error types
        for error_type, count in error_patterns.items():
            if count > 3:
                insights.append(f"Frequent {error_type} errors detected ({count} occurrences)")
        
        # Analyze health status
        health = health_status.get("health_status", "unknown")
        if health == "unhealthy":
            insights.append("Monitor tools health is unhealthy - immediate attention required")
        elif health == "degraded":
            insights.append("Monitor tools health is degraded - performance may be impacted")
        
        return insights
    
    def _generate_operational_recommendations(
        self,
        error_stats: Dict[str, Any],
        health_status: Dict[str, Any]
    ) -> List[str]:
        """Generate operational recommendations based on current status.
        
        Args:
            error_stats: Error statistics dictionary
            health_status: Health status dictionary
            
        Returns:
            List of operational recommendations
        """
        recommendations = []
        
        # Get health recommendations
        health_recommendations = health_status.get("recommendations", [])
        recommendations.extend(health_recommendations)
        
        # Add specific recommendations based on error patterns
        error_patterns = error_stats.get("monitor_tools_errors", {}).get("error_patterns", {})
        
        for error_type, count in error_patterns.items():
            if "rate_limit" in error_type.lower() and count > 2:
                recommendations.append("Consider implementing request throttling or increasing rate limits")
            elif "timeout" in error_type.lower() and count > 2:
                recommendations.append("Consider increasing timeout values or optimizing query performance")
            elif "validation" in error_type.lower() and count > 3:
                recommendations.append("Review monitor configuration validation rules and user guidance")
            elif "permission" in error_type.lower() and count > 1:
                recommendations.append("Review user permissions and access control settings")
        
        # Add general recommendations
        total_errors = error_stats.get("monitor_tools_errors", {}).get("total_errors", 0)
        if total_errors > 10:
            recommendations.append("Consider implementing additional monitoring and alerting for monitor tools")
            recommendations.append("Review error handling patterns and retry logic configuration")
        
        if not recommendations:
            recommendations.append("System is operating normally - continue monitoring")
        
        return recommendations