"""
Collector tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic collector and source management
including listing, creating, updating, and deleting collectors and sources.
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError
from ..models.responses import CollectorInfo

logger = logging.getLogger(__name__)


class CollectorTools:
    """MCP tools for Sumo Logic collector management."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize CollectorTools with API client.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
    
    async def list_collectors(
        self,
        filter_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List all collectors with optional filtering.
        
        This tool retrieves a list of collectors from Sumo Logic with support
        for type-based filtering and pagination.
        
        Args:
            filter_type: Optional collector type filter (Installable, Hosted, etc.)
            limit: Maximum number of collectors to return (1-1000)
            offset: Starting position for pagination (0-based)
            
        Returns:
            Dict containing collector list and metadata:
            {
                "collectors": List[Dict],
                "total_count": int,
                "offset": int,
                "limit": int,
                "has_more": bool,
                "collector_types": Dict[str, int]
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If collector listing fails
        """
        try:
            # Validate parameters
            if limit < 1 or limit > 1000:
                raise ValidationError("Limit must be between 1 and 1000")
            
            if offset < 0:
                raise ValidationError("Offset must be non-negative")
            
            valid_types = ["Installable", "Hosted", "All"]
            if filter_type and filter_type not in valid_types:
                raise ValidationError(f"filter_type must be one of: {', '.join(valid_types)}")
            
            logger.info(f"Listing collectors with type='{filter_type}', limit={limit}, offset={offset}")
            
            # Get collectors from API
            collectors_response = await self.api_client.list_collectors(
                filter_type=filter_type,
                limit=limit,
                offset=offset
            )
            
            # Extract collector data
            collectors = collectors_response.get("collectors", [])
            total_count = collectors_response.get("totalCount", len(collectors))
            
            # Format collector entries and collect statistics
            formatted_collectors = []
            collector_types = {}
            
            for collector in collectors:
                collector_type = collector.get("collectorType", "Unknown")
                collector_types[collector_type] = collector_types.get(collector_type, 0) + 1
                
                formatted_collector = {
                    "id": collector.get("id"),
                    "name": collector.get("name", ""),
                    "description": collector.get("description", ""),
                    "collector_type": collector_type,
                    "collector_version": collector.get("collectorVersion", ""),
                    "status": collector.get("alive", False),
                    "last_seen_alive": collector.get("lastSeenAlive"),
                    "host_name": collector.get("hostName", ""),
                    "source_count": len(collector.get("sources", [])),
                    "category": collector.get("category", ""),
                    "time_zone": collector.get("timeZone", ""),
                    "links": collector.get("links", []),
                    "ephemeral": collector.get("ephemeral", False),
                    "source_sync_mode": collector.get("sourceSyncMode", "")
                }
                formatted_collectors.append(formatted_collector)
            
            # Determine if there are more results
            has_more = (offset + len(formatted_collectors)) < total_count
            
            return {
                "collectors": formatted_collectors,
                "total_count": total_count,
                "offset": offset,
                "limit": limit,
                "returned_count": len(formatted_collectors),
                "has_more": has_more,
                "filter_applied": filter_type is not None,
                "collector_types": collector_types,
                "summary": {
                    "online_collectors": sum(1 for c in formatted_collectors if c["status"]),
                    "offline_collectors": sum(1 for c in formatted_collectors if not c["status"]),
                    "total_sources": sum(c["source_count"] for c in formatted_collectors)
                }
            }
            
        except ValidationError as e:
            logger.error(f"Collector listing validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Collector listing API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error listing collectors: {e}")
            raise APIError(f"Failed to list collectors: {str(e)}")
    
    async def get_collector(self, collector_id: str) -> Dict[str, Any]:
        """Get collector details and configuration.
        
        This tool retrieves detailed information about a specific collector
        including its configuration, sources, and status.
        
        Args:
            collector_id: Unique identifier for the collector
            
        Returns:
            Dict containing complete collector information:
            {
                "id": str,
                "name": str,
                "collector_type": str,
                "status": bool,
                "sources": List[Dict],
                "configuration": Dict,
                "statistics": Dict
            }
            
        Raises:
            ValidationError: If collector_id is invalid
            APIError: If collector retrieval fails
        """
        try:
            if not collector_id or not isinstance(collector_id, str):
                raise ValidationError("Collector ID must be a non-empty string")
            
            logger.info(f"Getting collector: {collector_id}")
            
            # Get collector from API
            collector_response = await self.api_client.get_collector(collector_id)
            
            # Format collector data
            collector = collector_response.get("collector", collector_response)
            
            # Get sources for this collector
            sources = collector.get("sources", [])
            formatted_sources = []
            
            for source in sources:
                formatted_source = {
                    "id": source.get("id"),
                    "name": source.get("name", ""),
                    "source_type": source.get("sourceType", ""),
                    "category": source.get("category", ""),
                    "host_name": source.get("hostName", ""),
                    "status": source.get("alive", False),
                    "last_seen_alive": source.get("lastSeenAlive"),
                    "message_count": source.get("messageCount", 0),
                    "error_count": source.get("errorCount", 0),
                    "configuration": source.get("config", {})
                }
                formatted_sources.append(formatted_source)
            
            # Calculate statistics
            statistics = {
                "total_sources": len(formatted_sources),
                "active_sources": sum(1 for s in formatted_sources if s["status"]),
                "inactive_sources": sum(1 for s in formatted_sources if not s["status"]),
                "total_messages": sum(s["message_count"] for s in formatted_sources),
                "total_errors": sum(s["error_count"] for s in formatted_sources),
                "source_types": {}
            }
            
            for source in formatted_sources:
                source_type = source["source_type"]
                statistics["source_types"][source_type] = statistics["source_types"].get(source_type, 0) + 1
            
            formatted_collector = {
                "id": collector.get("id"),
                "name": collector.get("name", ""),
                "description": collector.get("description", ""),
                "collector_type": collector.get("collectorType", ""),
                "collector_version": collector.get("collectorVersion", ""),
                "status": collector.get("alive", False),
                "last_seen_alive": collector.get("lastSeenAlive"),
                "host_name": collector.get("hostName", ""),
                "operating_system": collector.get("osName", ""),
                "os_version": collector.get("osVersion", ""),
                "os_arch": collector.get("osArch", ""),
                "category": collector.get("category", ""),
                "time_zone": collector.get("timeZone", ""),
                "ephemeral": collector.get("ephemeral", False),
                "source_sync_mode": collector.get("sourceSyncMode", ""),
                "links": collector.get("links", []),
                "sources": formatted_sources,
                "statistics": statistics,
                "configuration": {
                    "cpu_target": collector.get("targetCpu"),
                    "disk_usage": collector.get("diskUsage"),
                    "fields": collector.get("fields", {}),
                    "cutoff_timestamp": collector.get("cutoffTimestamp"),
                    "cutoff_relative_time": collector.get("cutoffRelativeTime")
                }
            }
            
            return formatted_collector
            
        except ValidationError as e:
            logger.error(f"Collector retrieval validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Collector retrieval API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting collector: {e}")
            raise APIError(f"Failed to get collector: {str(e)}")
    
    async def create_collector(
        self,
        name: str,
        collector_type: str,
        description: str = "",
        category: Optional[str] = None,
        host_name: Optional[str] = None,
        time_zone: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create new collector with specified configuration.
        
        This tool creates a new collector in Sumo Logic with comprehensive
        configuration validation.
        
        Args:
            name: Collector name (required)
            collector_type: Type of collector (Installable, Hosted)
            description: Collector description
            category: Default category for sources
            host_name: Host name for the collector
            time_zone: Time zone for the collector
            fields: Custom fields for the collector
            
        Returns:
            Dict containing created collector information:
            {
                "id": str,
                "name": str,
                "collector_type": str,
                "created_at": str,
                "registration_url": str
            }
            
        Raises:
            ValidationError: If collector configuration is invalid
            APIError: If collector creation fails
        """
        try:
            # Validate required parameters
            if not name or not isinstance(name, str) or len(name.strip()) == 0:
                raise ValidationError("Collector name must be a non-empty string")
            
            if len(name) > 128:
                raise ValidationError("Collector name must be 128 characters or less")
            
            valid_types = ["Installable", "Hosted"]
            if collector_type not in valid_types:
                raise ValidationError(f"collector_type must be one of: {', '.join(valid_types)}")
            
            # Validate optional parameters
            if category and len(category) > 1024:
                raise ValidationError("Category must be 1024 characters or less")
            
            if host_name and len(host_name) > 128:
                raise ValidationError("Host name must be 128 characters or less")
            
            if fields and not isinstance(fields, dict):
                raise ValidationError("Fields must be a dictionary")
            
            logger.info(f"Creating collector: {name} ({collector_type})")
            
            # Prepare collector configuration
            collector_config = {
                "name": name.strip(),
                "collectorType": collector_type,
                "description": description
            }
            
            if category:
                collector_config["category"] = category
            
            if host_name:
                collector_config["hostName"] = host_name
            
            if time_zone:
                collector_config["timeZone"] = time_zone
            
            if fields:
                collector_config["fields"] = fields
            
            # Create collector via API
            create_response = await self.api_client.create_collector(collector_config)
            
            # Format response
            created_collector = create_response.get("collector", create_response)
            
            formatted_response = {
                "id": created_collector.get("id"),
                "name": created_collector.get("name"),
                "collector_type": created_collector.get("collectorType"),
                "description": created_collector.get("description", ""),
                "category": created_collector.get("category", ""),
                "host_name": created_collector.get("hostName", ""),
                "time_zone": created_collector.get("timeZone", ""),
                "created_at": datetime.now().isoformat(),
                "status": "created",
                "ephemeral": created_collector.get("ephemeral", False),
                "links": created_collector.get("links", []),
                "registration_url": self._extract_registration_url(created_collector.get("links", []))
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Collector creation validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Collector creation API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating collector: {e}")
            raise APIError(f"Failed to create collector: {str(e)}")
    
    async def update_collector(
        self,
        collector_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        host_name: Optional[str] = None,
        time_zone: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Update collector configuration.
        
        This tool updates an existing collector with new configuration,
        supporting partial updates of collector properties.
        
        Args:
            collector_id: Unique identifier for the collector to update
            name: New collector name (optional)
            description: New collector description (optional)
            category: New default category (optional)
            host_name: New host name (optional)
            time_zone: New time zone (optional)
            fields: New custom fields (optional)
            
        Returns:
            Dict containing updated collector information:
            {
                "id": str,
                "name": str,
                "modified_at": str,
                "changes_applied": List[str]
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If collector update fails
        """
        try:
            if not collector_id or not isinstance(collector_id, str):
                raise ValidationError("Collector ID must be a non-empty string")
            
            # Get current collector configuration
            current_collector = await self.get_collector(collector_id)
            
            # Prepare update payload with only changed fields
            update_config = {}
            changes_applied = []
            
            if name is not None:
                if not isinstance(name, str) or len(name.strip()) == 0:
                    raise ValidationError("Name must be a non-empty string")
                if len(name) > 128:
                    raise ValidationError("Name must be 128 characters or less")
                update_config["name"] = name.strip()
                changes_applied.append("name")
            
            if description is not None:
                update_config["description"] = description
                changes_applied.append("description")
            
            if category is not None:
                if len(category) > 1024:
                    raise ValidationError("Category must be 1024 characters or less")
                update_config["category"] = category
                changes_applied.append("category")
            
            if host_name is not None:
                if len(host_name) > 128:
                    raise ValidationError("Host name must be 128 characters or less")
                update_config["hostName"] = host_name
                changes_applied.append("host_name")
            
            if time_zone is not None:
                update_config["timeZone"] = time_zone
                changes_applied.append("time_zone")
            
            if fields is not None:
                if not isinstance(fields, dict):
                    raise ValidationError("Fields must be a dictionary")
                update_config["fields"] = fields
                changes_applied.append("fields")
            
            if not changes_applied:
                raise ValidationError("At least one field must be provided for update")
            
            logger.info(f"Updating collector {collector_id} with changes: {changes_applied}")
            
            # Update collector via API
            update_response = await self.api_client.update_collector(collector_id, update_config)
            
            # Format response
            updated_collector = update_response.get("collector", update_response)
            
            formatted_response = {
                "id": updated_collector.get("id"),
                "name": updated_collector.get("name"),
                "description": updated_collector.get("description", ""),
                "collector_type": updated_collector.get("collectorType"),
                "modified_at": datetime.now().isoformat(),
                "changes_applied": changes_applied,
                "status": updated_collector.get("alive", False),
                "version": updated_collector.get("version")
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Collector update validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Collector update API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating collector: {e}")
            raise APIError(f"Failed to update collector: {str(e)}")
    
    async def delete_collector(self, collector_id: str) -> Dict[str, Any]:
        """Delete specified collector.
        
        This tool permanently deletes a collector from Sumo Logic.
        
        Args:
            collector_id: Unique identifier for the collector to delete
            
        Returns:
            Dict containing deletion confirmation:
            {
                "id": str,
                "deleted": bool,
                "deleted_at": str,
                "name": str
            }
            
        Raises:
            ValidationError: If collector_id is invalid
            APIError: If collector deletion fails
        """
        try:
            if not collector_id or not isinstance(collector_id, str):
                raise ValidationError("Collector ID must be a non-empty string")
            
            # Get collector info before deletion for confirmation
            collector_info = await self.get_collector(collector_id)
            collector_name = collector_info.get("name", "Unknown")
            source_count = len(collector_info.get("sources", []))
            
            if source_count > 0:
                logger.warning(f"Deleting collector {collector_id} with {source_count} sources")
            
            logger.info(f"Deleting collector: {collector_id} ({collector_name})")
            
            # Delete collector via API
            delete_response = await self.api_client.delete_collector(collector_id)
            
            # Format response
            formatted_response = {
                "id": collector_id,
                "deleted": True,
                "deleted_at": datetime.now().isoformat(),
                "name": collector_name,
                "sources_deleted": source_count,
                "message": f"Collector '{collector_name}' and {source_count} sources have been successfully deleted"
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Collector deletion validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Collector deletion API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting collector: {e}")
            raise APIError(f"Failed to delete collector: {str(e)}")
    
    async def list_sources(
        self,
        collector_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List sources for specified collector.
        
        This tool retrieves all sources configured for a specific collector
        with pagination support.
        
        Args:
            collector_id: Unique identifier for the collector
            limit: Maximum number of sources to return (1-1000)
            offset: Starting position for pagination (0-based)
            
        Returns:
            Dict containing source list and metadata:
            {
                "collector_id": str,
                "sources": List[Dict],
                "total_count": int,
                "source_types": Dict[str, int]
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If source listing fails
        """
        try:
            if not collector_id or not isinstance(collector_id, str):
                raise ValidationError("Collector ID must be a non-empty string")
            
            if limit < 1 or limit > 1000:
                raise ValidationError("Limit must be between 1 and 1000")
            
            if offset < 0:
                raise ValidationError("Offset must be non-negative")
            
            logger.info(f"Listing sources for collector {collector_id}")
            
            # Get sources from API
            sources_response = await self.api_client.list_sources(
                collector_id=collector_id,
                limit=limit,
                offset=offset
            )
            
            # Extract and format source data
            sources = sources_response.get("sources", [])
            source_types = {}
            
            formatted_sources = []
            for source in sources:
                source_type = source.get("sourceType", "Unknown")
                source_types[source_type] = source_types.get(source_type, 0) + 1
                
                formatted_source = {
                    "id": source.get("id"),
                    "name": source.get("name", ""),
                    "source_type": source_type,
                    "category": source.get("category", ""),
                    "host_name": source.get("hostName", ""),
                    "status": source.get("alive", False),
                    "last_seen_alive": source.get("lastSeenAlive"),
                    "message_count": source.get("messageCount", 0),
                    "error_count": source.get("errorCount", 0),
                    "created_at": source.get("createdAt"),
                    "modified_at": source.get("modifiedAt"),
                    "configuration_summary": self._summarize_source_config(source.get("config", {}))
                }
                formatted_sources.append(formatted_source)
            
            return {
                "collector_id": collector_id,
                "sources": formatted_sources,
                "total_count": len(formatted_sources),
                "offset": offset,
                "limit": limit,
                "source_types": source_types,
                "summary": {
                    "active_sources": sum(1 for s in formatted_sources if s["status"]),
                    "inactive_sources": sum(1 for s in formatted_sources if not s["status"]),
                    "total_messages": sum(s["message_count"] for s in formatted_sources),
                    "total_errors": sum(s["error_count"] for s in formatted_sources)
                }
            }
            
        except ValidationError as e:
            logger.error(f"Source listing validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Source listing API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error listing sources: {e}")
            raise APIError(f"Failed to list sources: {str(e)}")
    
    async def create_source(
        self,
        collector_id: str,
        source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create new source in specified collector.
        
        This tool creates a new source within an existing collector with
        comprehensive configuration validation.
        
        Args:
            collector_id: Unique identifier for the collector
            source_config: Complete source configuration dictionary
            
        Returns:
            Dict containing created source information:
            {
                "id": str,
                "name": str,
                "source_type": str,
                "collector_id": str,
                "created_at": str
            }
            
        Raises:
            ValidationError: If source configuration is invalid
            APIError: If source creation fails
        """
        try:
            if not collector_id or not isinstance(collector_id, str):
                raise ValidationError("Collector ID must be a non-empty string")
            
            if not source_config or not isinstance(source_config, dict):
                raise ValidationError("Source config must be a non-empty dictionary")
            
            # Validate required source configuration fields
            required_fields = ["name", "sourceType"]
            for field in required_fields:
                if field not in source_config:
                    raise ValidationError(f"Source config must include '{field}' field")
            
            source_name = source_config.get("name", "")
            if not source_name or len(source_name.strip()) == 0:
                raise ValidationError("Source name must be a non-empty string")
            
            if len(source_name) > 128:
                raise ValidationError("Source name must be 128 characters or less")
            
            source_type = source_config.get("sourceType", "")
            valid_source_types = [
                "LocalFile", "RemoteFile", "Syslog", "LocalWindowsEventLog",
                "RemoteWindowsEventLog", "Script", "StreamingMetrics", "HTTP"
            ]
            
            if source_type not in valid_source_types:
                logger.warning(f"Unknown source type: {source_type}")
            
            logger.info(f"Creating source '{source_name}' ({source_type}) in collector {collector_id}")
            
            # Create source via API
            create_response = await self.api_client.create_source(collector_id, source_config)
            
            # Format response
            created_source = create_response.get("source", create_response)
            
            formatted_response = {
                "id": created_source.get("id"),
                "name": created_source.get("name"),
                "source_type": created_source.get("sourceType"),
                "collector_id": collector_id,
                "category": created_source.get("category", ""),
                "host_name": created_source.get("hostName", ""),
                "created_at": datetime.now().isoformat(),
                "status": "created",
                "configuration": created_source.get("config", {}),
                "url": f"/ui/collector/{collector_id}/source/{created_source.get('id')}" if created_source.get('id') else None
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Source creation validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Source creation API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating source: {e}")
            raise APIError(f"Failed to create source: {str(e)}")
    
    def _extract_registration_url(self, links: List[Dict[str, Any]]) -> Optional[str]:
        """Extract registration URL from collector links.
        
        Args:
            links: List of link objects from collector response
            
        Returns:
            Registration URL if found, None otherwise
        """
        for link in links:
            if link.get("rel") == "edit" or "registration" in link.get("href", ""):
                return link.get("href")
        return None
    
    def _summarize_source_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize source configuration for display.
        
        Args:
            config: Source configuration dictionary
            
        Returns:
            Summarized configuration
        """
        summary = {}
        
        # Common configuration fields to include in summary
        summary_fields = [
            "pathExpression", "blacklist", "encoding", "multilineProcessingEnabled",
            "useAutolineMatching", "manualPrefixRegexp", "forceTimeZone", "defaultDateFormat"
        ]
        
        for field in summary_fields:
            if field in config:
                summary[field] = config[field]
        
        return summary
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for collector operations.
        
        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "list_collectors",
                "description": "List all collectors with optional filtering and pagination",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter_type": {
                            "type": "string",
                            "description": "Optional collector type filter",
                            "enum": ["Installable", "Hosted", "All"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of collectors to return (1-1000)",
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
                    "required": []
                }
            },
            {
                "name": "get_collector",
                "description": "Get detailed collector information including sources and statistics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collector_id": {
                            "type": "string",
                            "description": "Unique identifier for the collector"
                        }
                    },
                    "required": ["collector_id"]
                }
            },
            {
                "name": "create_collector",
                "description": "Create new collector with specified configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Collector name (required, max 128 characters)"
                        },
                        "collector_type": {
                            "type": "string",
                            "description": "Type of collector",
                            "enum": ["Installable", "Hosted"]
                        },
                        "description": {
                            "type": "string",
                            "description": "Collector description",
                            "default": ""
                        },
                        "category": {
                            "type": "string",
                            "description": "Default category for sources (max 1024 characters)"
                        },
                        "host_name": {
                            "type": "string",
                            "description": "Host name for the collector (max 128 characters)"
                        },
                        "time_zone": {
                            "type": "string",
                            "description": "Time zone for the collector"
                        },
                        "fields": {
                            "type": "object",
                            "description": "Custom fields for the collector",
                            "additionalProperties": {"type": "string"}
                        }
                    },
                    "required": ["name", "collector_type"]
                }
            },
            {
                "name": "update_collector",
                "description": "Update existing collector configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collector_id": {
                            "type": "string",
                            "description": "Unique identifier for the collector to update"
                        },
                        "name": {
                            "type": "string",
                            "description": "New collector name (max 128 characters)"
                        },
                        "description": {
                            "type": "string",
                            "description": "New collector description"
                        },
                        "category": {
                            "type": "string",
                            "description": "New default category (max 1024 characters)"
                        },
                        "host_name": {
                            "type": "string",
                            "description": "New host name (max 128 characters)"
                        },
                        "time_zone": {
                            "type": "string",
                            "description": "New time zone"
                        },
                        "fields": {
                            "type": "object",
                            "description": "New custom fields",
                            "additionalProperties": {"type": "string"}
                        }
                    },
                    "required": ["collector_id"]
                }
            },
            {
                "name": "delete_collector",
                "description": "Delete specified collector and all its sources permanently",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collector_id": {
                            "type": "string",
                            "description": "Unique identifier for the collector to delete"
                        }
                    },
                    "required": ["collector_id"]
                }
            },
            {
                "name": "list_sources",
                "description": "List sources for specified collector with pagination",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collector_id": {
                            "type": "string",
                            "description": "Unique identifier for the collector"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of sources to return (1-1000)",
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
                    "required": ["collector_id"]
                }
            },
            {
                "name": "create_source",
                "description": "Create new source in specified collector",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "collector_id": {
                            "type": "string",
                            "description": "Unique identifier for the collector"
                        },
                        "source_config": {
                            "type": "object",
                            "description": "Complete source configuration dictionary",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Source name (required, max 128 characters)"
                                },
                                "sourceType": {
                                    "type": "string",
                                    "description": "Type of source (LocalFile, RemoteFile, Syslog, etc.)"
                                },
                                "category": {
                                    "type": "string",
                                    "description": "Source category"
                                },
                                "hostName": {
                                    "type": "string",
                                    "description": "Host name for the source"
                                }
                            },
                            "required": ["name", "sourceType"],
                            "additionalProperties": True
                        }
                    },
                    "required": ["collector_id", "source_config"]
                }
            }
        ]