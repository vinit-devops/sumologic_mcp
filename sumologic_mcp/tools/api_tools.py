"""
API tools for Sumo Logic MCP server.

This module implements the generic api_call MCP tool to hit any raw Sumo Logic API endpoint.
"""

import logging
from typing import Any, Dict, List, Optional

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError

logger = logging.getLogger(__name__)


class APITools:
    """MCP tools for generic Sumo Logic API operations."""

    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize APITools with API client.

        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client

    async def api_call(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute a raw HTTP request to any Sumo Logic API endpoint.

        This tool executes a raw HTTP request (GET, POST, PUT, DELETE, PATCH)
        against the specified Sumo Logic API endpoint using the configured credentials.

        Args:
            method: HTTP method to use (GET, POST, PUT, DELETE, PATCH)
            path: The API endpoint path (e.g. '/v1/users', '/v1/folders/0000000000000002')
            params: Optional query parameters to include in the URL
            body: Optional JSON request body for POST/PUT/PATCH/DELETE requests
            headers: Optional custom headers to include in the request

        Returns:
            Dict containing response status_code, headers, and parsed body.

        Raises:
            ValidationError: If path or method is invalid
            APIError: If the request execution fails
        """
        # Validate path and method
        if not path or not isinstance(path, str):
            raise ValidationError(
                "Path must be a non-empty string", field_name="path", field_value=path
            )

        valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        if not method or method.upper() not in valid_methods:
            raise ValidationError(
                f"Method must be one of: {', '.join(valid_methods)}",
                field_name="method",
                field_value=method,
            )

        logger.info(f"Executing raw API call: {method.upper()} {path}")

        return await self.api_client.execute_raw_request(
            method=method, path=path, params=params, body=body, headers=headers
        )

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for API operations.

        Returns:
            List of tool definitions for MCP server registration
        """
        return [
            {
                "name": "api_call",
                "description": (
                    "Execute a raw, authenticated HTTP request to any Sumo Logic API endpoint. "
                    "Use this tool when you need to access Sumo Logic API endpoints that do not "
                    "have dedicated MCP tools (e.g. user/role management, folders, partitions, "
                    "connections, ingestion keys, content import/export, etc.)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "description": "HTTP method to use (GET, POST, PUT, DELETE, PATCH)",
                            "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "The API endpoint path starting with a slash (e.g., '/v1/users', "
                                "'/v1/folders/0000000000000002'). Do not include the base URL."
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": "Optional query parameters as key-value pairs",
                        },
                        "body": {
                            "type": "object",
                            "description": "Optional JSON request body for POST/PUT/PATCH/DELETE requests",
                        },
                        "headers": {
                            "type": "object",
                            "description": "Optional custom headers as key-value pairs",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["method", "path"],
                },
            }
        ]
