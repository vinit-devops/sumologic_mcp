"""
Dashboard tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic dashboard operations including
listing, creating, updating, and deleting dashboards with configuration validation.
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError
from ..models.config import DashboardConfig
from ..models.responses import DashboardInfo

logger = logging.getLogger(__name__)


class DashboardTools:
    """MCP tools for Sumo Logic dashboard operations."""
    
    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize DashboardTools with API client.
        
        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client
    
    async def list_dashboards(
        self,
        filter_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List all available dashboards with optional filtering.
        
        This tool retrieves a list of dashboards from Sumo Logic with support
        for name-based filtering and pagination.
        
        Args:
            filter_name: Optional name filter to search for specific dashboards
            limit: Maximum number of dashboards to return (1-1000)
            offset: Starting position for pagination (0-based)
            
        Returns:
            Dict containing dashboard list and metadata:
            {
                "dashboards": List[Dict],
                "total_count": int,
                "offset": int,
                "limit": int,
                "has_more": bool
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If dashboard listing fails
        """
        try:
            # Validate parameters
            if limit < 1 or limit > 1000:
                raise ValidationError("Limit must be between 1 and 1000")
            
            if offset < 0:
                raise ValidationError("Offset must be non-negative")
            
            logger.info(f"Listing dashboards with filter='{filter_name}', limit={limit}, offset={offset}")
            
            # Get dashboards from API
            dashboards_response = await self.api_client.list_dashboards(
                filter_name=filter_name,
                limit=limit,
                offset=offset
            )
            
            # Extract dashboard data
            dashboards = dashboards_response.get("data", [])
            total_count = dashboards_response.get("totalCount", len(dashboards))
            
            # Format dashboard entries
            formatted_dashboards = []
            for dashboard in dashboards:
                formatted_dashboard = {
                    "id": dashboard.get("id"),
                    "title": dashboard.get("title", ""),
                    "description": dashboard.get("description", ""),
                    "folder_id": dashboard.get("folderId"),
                    "created_at": dashboard.get("createdAt"),
                    "created_by": dashboard.get("createdBy"),
                    "modified_at": dashboard.get("modifiedAt"),
                    "modified_by": dashboard.get("modifiedBy"),
                    "version": dashboard.get("version", 1),
                    "panel_count": len(dashboard.get("panels", [])),
                    "refresh_interval": dashboard.get("refreshInterval")
                }
                formatted_dashboards.append(formatted_dashboard)
            
            # Determine if there are more results
            has_more = (offset + len(formatted_dashboards)) < total_count
            
            return {
                "dashboards": formatted_dashboards,
                "total_count": total_count,
                "offset": offset,
                "limit": limit,
                "returned_count": len(formatted_dashboards),
                "has_more": has_more,
                "filter_applied": filter_name is not None
            }
            
        except ValidationError as e:
            logger.error(f"Dashboard listing validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Dashboard listing API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error listing dashboards: {e}")
            raise APIError(f"Failed to list dashboards: {str(e)}")
    
    async def get_dashboard(self, dashboard_id: str) -> Dict[str, Any]:
        """Get dashboard configuration and metadata.
        
        This tool retrieves detailed information about a specific dashboard
        including its configuration, panels, and metadata.
        
        Args:
            dashboard_id: Unique identifier for the dashboard
            
        Returns:
            Dict containing complete dashboard information:
            {
                "id": str,
                "title": str,
                "description": str,
                "panels": List[Dict],
                "layout": Dict,
                "variables": List[Dict],
                "created_at": str,
                "modified_at": str,
                "version": int
            }
            
        Raises:
            ValidationError: If dashboard_id is invalid
            APIError: If dashboard retrieval fails
        """
        try:
            if not dashboard_id or not isinstance(dashboard_id, str):
                raise ValidationError("Dashboard ID must be a non-empty string")
            
            logger.info(f"Getting dashboard: {dashboard_id}")
            
            # Get dashboard from API
            dashboard_response = await self.api_client.get_dashboard(dashboard_id)
            
            # Format dashboard data
            dashboard = dashboard_response.get("dashboard", dashboard_response)
            
            formatted_dashboard = {
                "id": dashboard.get("id"),
                "title": dashboard.get("title", ""),
                "description": dashboard.get("description", ""),
                "folder_id": dashboard.get("folderId"),
                "panels": dashboard.get("panels", []),
                "layout": dashboard.get("layout", {}),
                "variables": dashboard.get("variables", []),
                "filters": dashboard.get("filters", []),
                "refresh_interval": dashboard.get("refreshInterval"),
                "time_range": dashboard.get("timeRange", {}),
                "created_at": dashboard.get("createdAt"),
                "created_by": dashboard.get("createdBy"),
                "modified_at": dashboard.get("modifiedAt"),
                "modified_by": dashboard.get("modifiedBy"),
                "version": dashboard.get("version", 1),
                "theme": dashboard.get("theme", "light")
            }
            
            # Add panel summary information
            panels = formatted_dashboard["panels"]
            panel_summary = {
                "total_panels": len(panels),
                "panel_types": {},
                "queries_count": 0
            }
            
            for panel in panels:
                panel_type = panel.get("panelType", "unknown")
                panel_summary["panel_types"][panel_type] = panel_summary["panel_types"].get(panel_type, 0) + 1
                
                # Count queries in panel
                queries = panel.get("queries", [])
                panel_summary["queries_count"] += len(queries)
            
            formatted_dashboard["panel_summary"] = panel_summary
            
            return formatted_dashboard
            
        except ValidationError as e:
            logger.error(f"Dashboard retrieval validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Dashboard retrieval API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting dashboard: {e}")
            raise APIError(f"Failed to get dashboard: {str(e)}")
    
    async def create_dashboard(
        self,
        title: str,
        description: str = "",
        panels: List[Dict[str, Any]] = None,
        folder_id: Optional[str] = None,
        refresh_interval: Optional[int] = None,
        time_range: Optional[Dict[str, Any]] = None,
        variables: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Create new dashboard with specified configuration.
        
        This tool creates a new dashboard in Sumo Logic with comprehensive
        configuration validation and panel setup.
        
        Args:
            title: Dashboard title (required)
            description: Dashboard description
            panels: List of panel configurations
            folder_id: ID of folder to create dashboard in
            refresh_interval: Auto-refresh interval in seconds
            time_range: Default time range for dashboard
            variables: Dashboard variables for dynamic queries
            
        Returns:
            Dict containing created dashboard information:
            {
                "id": str,
                "title": str,
                "description": str,
                "created_at": str,
                "version": int,
                "url": str
            }
            
        Raises:
            ValidationError: If dashboard configuration is invalid
            APIError: If dashboard creation fails
        """
        try:
            # Validate required parameters
            if not title or not isinstance(title, str) or len(title.strip()) == 0:
                raise ValidationError("Dashboard title must be a non-empty string")
            
            if len(title) > 255:
                raise ValidationError("Dashboard title must be 255 characters or less")
            
            # Validate optional parameters
            if panels is None:
                panels = []
            
            if not isinstance(panels, list):
                raise ValidationError("Panels must be a list")
            
            if refresh_interval is not None and (refresh_interval < 30 or refresh_interval > 86400):
                raise ValidationError("Refresh interval must be between 30 and 86400 seconds")
            
            # Validate panel configurations
            for i, panel in enumerate(panels):
                if not isinstance(panel, dict):
                    raise ValidationError(f"Panel {i} must be a dictionary")
                
                if "panelType" not in panel:
                    raise ValidationError(f"Panel {i} must have a panelType")
                
                if "title" not in panel:
                    raise ValidationError(f"Panel {i} must have a title")
            
            logger.info(f"Creating dashboard: {title}")
            
            # Prepare dashboard configuration
            dashboard_config = {
                "title": title.strip(),
                "description": description,
                "panels": panels,
                "refreshInterval": refresh_interval,
                "timeRange": time_range or {
                    "type": "BeginBoundedTimeRange",
                    "from": {
                        "type": "RelativeTimeRangeBoundary",
                        "relativeTime": "-1h"
                    },
                    "to": None
                },
                "variables": variables or [],
                "layout": {
                    "layoutType": "Grid",
                    "layoutStructures": []
                }
            }
            
            if folder_id:
                dashboard_config["folderId"] = folder_id
            
            # Validate using Pydantic model
            validated_config = DashboardConfig(
                title=title,
                description=description,
                panels=panels,
                refresh_interval=refresh_interval
            )
            
            # Create dashboard via API
            create_response = await self.api_client.create_dashboard(dashboard_config)
            
            # Format response
            created_dashboard = create_response.get("dashboard", create_response)
            
            formatted_response = {
                "id": created_dashboard.get("id"),
                "title": created_dashboard.get("title"),
                "description": created_dashboard.get("description", ""),
                "folder_id": created_dashboard.get("folderId"),
                "created_at": created_dashboard.get("createdAt"),
                "created_by": created_dashboard.get("createdBy"),
                "version": created_dashboard.get("version", 1),
                "panel_count": len(panels),
                "refresh_interval": refresh_interval,
                "url": f"/ui/dashboard/{created_dashboard.get('id')}" if created_dashboard.get('id') else None
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Dashboard creation validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Dashboard creation API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating dashboard: {e}")
            raise APIError(f"Failed to create dashboard: {str(e)}")
    
    async def update_dashboard(
        self,
        dashboard_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        panels: Optional[List[Dict[str, Any]]] = None,
        refresh_interval: Optional[int] = None,
        time_range: Optional[Dict[str, Any]] = None,
        variables: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Update existing dashboard configuration.
        
        This tool updates an existing dashboard with new configuration,
        supporting partial updates of dashboard properties.
        
        Args:
            dashboard_id: Unique identifier for the dashboard to update
            title: New dashboard title (optional)
            description: New dashboard description (optional)
            panels: New panel configurations (optional)
            refresh_interval: New auto-refresh interval (optional)
            time_range: New default time range (optional)
            variables: New dashboard variables (optional)
            
        Returns:
            Dict containing updated dashboard information:
            {
                "id": str,
                "title": str,
                "description": str,
                "modified_at": str,
                "version": int,
                "changes_applied": List[str]
            }
            
        Raises:
            ValidationError: If parameters are invalid
            APIError: If dashboard update fails
        """
        try:
            if not dashboard_id or not isinstance(dashboard_id, str):
                raise ValidationError("Dashboard ID must be a non-empty string")
            
            # Get current dashboard configuration
            current_dashboard = await self.get_dashboard(dashboard_id)
            
            # Prepare update payload with only changed fields
            update_config = {}
            changes_applied = []
            
            if title is not None:
                if not isinstance(title, str) or len(title.strip()) == 0:
                    raise ValidationError("Title must be a non-empty string")
                if len(title) > 255:
                    raise ValidationError("Title must be 255 characters or less")
                update_config["title"] = title.strip()
                changes_applied.append("title")
            
            if description is not None:
                update_config["description"] = description
                changes_applied.append("description")
            
            if panels is not None:
                if not isinstance(panels, list):
                    raise ValidationError("Panels must be a list")
                
                # Validate panel configurations
                for i, panel in enumerate(panels):
                    if not isinstance(panel, dict):
                        raise ValidationError(f"Panel {i} must be a dictionary")
                    if "panelType" not in panel:
                        raise ValidationError(f"Panel {i} must have a panelType")
                    if "title" not in panel:
                        raise ValidationError(f"Panel {i} must have a title")
                
                update_config["panels"] = panels
                changes_applied.append("panels")
            
            if refresh_interval is not None:
                if refresh_interval < 30 or refresh_interval > 86400:
                    raise ValidationError("Refresh interval must be between 30 and 86400 seconds")
                update_config["refreshInterval"] = refresh_interval
                changes_applied.append("refresh_interval")
            
            if time_range is not None:
                update_config["timeRange"] = time_range
                changes_applied.append("time_range")
            
            if variables is not None:
                if not isinstance(variables, list):
                    raise ValidationError("Variables must be a list")
                update_config["variables"] = variables
                changes_applied.append("variables")
            
            if not changes_applied:
                raise ValidationError("At least one field must be provided for update")
            
            logger.info(f"Updating dashboard {dashboard_id} with changes: {changes_applied}")
            
            # Update dashboard via API
            update_response = await self.api_client.update_dashboard(dashboard_id, update_config)
            
            # Format response
            updated_dashboard = update_response.get("dashboard", update_response)
            
            formatted_response = {
                "id": updated_dashboard.get("id"),
                "title": updated_dashboard.get("title"),
                "description": updated_dashboard.get("description", ""),
                "modified_at": updated_dashboard.get("modifiedAt"),
                "modified_by": updated_dashboard.get("modifiedBy"),
                "version": updated_dashboard.get("version"),
                "changes_applied": changes_applied,
                "panel_count": len(updated_dashboard.get("panels", [])),
                "refresh_interval": updated_dashboard.get("refreshInterval")
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Dashboard update validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Dashboard update API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating dashboard: {e}")
            raise APIError(f"Failed to update dashboard: {str(e)}")
    
    async def delete_dashboard(self, dashboard_id: str) -> Dict[str, Any]:
        """Delete specified dashboard.
        
        This tool permanently deletes a dashboard from Sumo Logic.
        
        Args:
            dashboard_id: Unique identifier for the dashboard to delete
            
        Returns:
            Dict containing deletion confirmation:
            {
                "id": str,
                "deleted": bool,
                "deleted_at": str,
                "title": str
            }
            
        Raises:
            ValidationError: If dashboard_id is invalid
            APIError: If dashboard deletion fails
        """
        try:
            if not dashboard_id or not isinstance(dashboard_id, str):
                raise ValidationError("Dashboard ID must be a non-empty string")
            
            # Get dashboard info before deletion for confirmation
            dashboard_info = await self.get_dashboard(dashboard_id)
            dashboard_title = dashboard_info.get("title", "Unknown")
            
            logger.info(f"Deleting dashboard: {dashboard_id} ({dashboard_title})")
            
            # Delete dashboard via API
            delete_response = await self.api_client.delete_dashboard(dashboard_id)
            
            # Format response
            formatted_response = {
                "id": dashboard_id,
                "deleted": True,
                "deleted_at": datetime.now().isoformat(),
                "title": dashboard_title,
                "message": f"Dashboard '{dashboard_title}' has been successfully deleted"
            }
            
            return formatted_response
            
        except ValidationError as e:
            logger.error(f"Dashboard deletion validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Dashboard deletion API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting dashboard: {e}")
            raise APIError(f"Failed to delete dashboard: {str(e)}")
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for dashboard operations.
        
        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "list_dashboards",
                "description": "List all available dashboards with optional filtering and pagination",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter_name": {
                            "type": "string",
                            "description": "Optional name filter to search for specific dashboards"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of dashboards to return (1-1000)",
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
                "name": "get_dashboard",
                "description": "Get detailed dashboard configuration and metadata",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dashboard_id": {
                            "type": "string",
                            "description": "Unique identifier for the dashboard"
                        }
                    },
                    "required": ["dashboard_id"]
                }
            },
            {
                "name": "create_dashboard",
                "description": "Create new dashboard with specified configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Dashboard title (required, max 255 characters)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Dashboard description",
                            "default": ""
                        },
                        "panels": {
                            "type": "array",
                            "description": "List of panel configurations",
                            "items": {"type": "object"},
                            "default": []
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "ID of folder to create dashboard in"
                        },
                        "refresh_interval": {
                            "type": "integer",
                            "description": "Auto-refresh interval in seconds (30-86400)",
                            "minimum": 30,
                            "maximum": 86400
                        },
                        "time_range": {
                            "type": "object",
                            "description": "Default time range for dashboard"
                        },
                        "variables": {
                            "type": "array",
                            "description": "Dashboard variables for dynamic queries",
                            "items": {"type": "object"},
                            "default": []
                        }
                    },
                    "required": ["title"]
                }
            },
            {
                "name": "update_dashboard",
                "description": "Update existing dashboard configuration",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dashboard_id": {
                            "type": "string",
                            "description": "Unique identifier for the dashboard to update"
                        },
                        "title": {
                            "type": "string",
                            "description": "New dashboard title (max 255 characters)"
                        },
                        "description": {
                            "type": "string",
                            "description": "New dashboard description"
                        },
                        "panels": {
                            "type": "array",
                            "description": "New panel configurations",
                            "items": {"type": "object"}
                        },
                        "refresh_interval": {
                            "type": "integer",
                            "description": "New auto-refresh interval in seconds (30-86400)",
                            "minimum": 30,
                            "maximum": 86400
                        },
                        "time_range": {
                            "type": "object",
                            "description": "New default time range"
                        },
                        "variables": {
                            "type": "array",
                            "description": "New dashboard variables",
                            "items": {"type": "object"}
                        }
                    },
                    "required": ["dashboard_id"]
                }
            },
            {
                "name": "delete_dashboard",
                "description": "Delete specified dashboard permanently",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dashboard_id": {
                            "type": "string",
                            "description": "Unique identifier for the dashboard to delete"
                        }
                    },
                    "required": ["dashboard_id"]
                }
            }
        ]