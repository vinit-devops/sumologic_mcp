"""Folder management tools for Sumo Logic MCP server.

This module implements MCP tools for Sumo Logic content library and folder operations.
"""

import asyncio
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from ..api_client import SumoLogicAPIClient
from ..exceptions import ValidationError, APIError

logger = logging.getLogger(__name__)


class FolderTools:
    """MCP tools for Sumo Logic content folder operations."""

    def __init__(self, api_client: SumoLogicAPIClient):
        """Initialize FolderTools with API client.

        Args:
            api_client: Configured SumoLogicAPIClient instance
        """
        self.api_client = api_client

    async def get_personal_folder_root(self) -> Dict[str, Any]:
        """Retrieve the user's personal content folder root.

        Returns:
            Dict containing personal folder configuration and contents.
        """
        try:
            logger.info("Retrieving personal folder root")
            return await self.api_client.get_personal_folder_root()
        except APIError as e:
            logger.error(f"Failed to get personal folder root: {e}")
            raise

    async def get_global_folder_root(self) -> Dict[str, Any]:
        """Retrieve the organization's global content folder root.

        Returns:
            Dict containing global folder configuration and contents.
        """
        try:
            logger.info("Retrieving global folder root")
            return await self.api_client.get_global_folder_root()
        except APIError as e:
            logger.error(f"Failed to get global folder root: {e}")
            raise

    async def get_folder(self, folder_id: str) -> Dict[str, Any]:
        """Retrieve a specific folder configuration and its contents by ID.

        Args:
            folder_id: Folder ID to retrieve

        Returns:
            Dict containing folder configuration and contents.
        """
        try:
            logger.info(f"Retrieving folder {folder_id}")
            return await self.api_client.get_folder(folder_id)
        except APIError as e:
            logger.error(f"Failed to get folder {folder_id}: {e}")
            raise

    async def create_folder(
        self, name: str, parent_id: str, description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new folder in the content library under a specified parent folder.

        Args:
            name: Folder name
            parent_id: Parent folder ID
            description: Optional folder description

        Returns:
            Dict containing created folder metadata.
        """
        try:
            logger.info(f"Creating folder '{name}' under parent {parent_id}")
            return await self.api_client.create_folder(
                name=name, parent_id=parent_id, description=description
            )
        except APIError as e:
            logger.error(f"Failed to create folder '{name}': {e}")
            raise

    async def delete_folder(
        self, folder_id: str, wait_for_completion: bool = True, timeout: int = 60
    ) -> Dict[str, Any]:
        """Delete a folder or content item by ID.

        Args:
            folder_id: Folder ID to delete
            wait_for_completion: Whether to wait for the deletion job to complete (default: True)
            timeout: Maximum wait time in seconds (default: 60)

        Returns:
            Dict containing deletion status/job ID.
        """
        try:
            logger.info(f"Deleting folder/content {folder_id}")
            job_response = await self.api_client.delete_folder_job(folder_id)
            job_id = job_response.get("id") or job_response.get("jobId")

            if not job_id:
                # If no job ID was returned, assume it completed synchronously or response had no ID
                return {
                    "status": "Success",
                    "folder_id": folder_id,
                    "message": "Deletion requested successfully.",
                }

            if not wait_for_completion:
                return {
                    "status": "InProgress",
                    "folder_id": folder_id,
                    "job_id": job_id,
                    "message": "Deletion job started asynchronously.",
                }

            # Polling status
            start_time = datetime.now()
            while True:
                status_response = await self.api_client.get_delete_folder_status(
                    folder_id, job_id
                )
                status = status_response.get("status", "InProgress")

                if status == "Success":
                    return {
                        "status": "Success",
                        "folder_id": folder_id,
                        "job_id": job_id,
                        "message": "Folder deleted successfully.",
                    }
                elif status == "Failed":
                    error_msg = status_response.get("error", {}).get("message", "Unknown error")
                    raise APIError(f"Folder deletion job failed: {error_msg}")

                # Check timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    raise APIError(
                        f"Folder deletion job {job_id} timed out after {timeout} seconds"
                    )

                await asyncio.sleep(2)

        except APIError as e:
            logger.error(f"Failed to delete folder {folder_id}: {e}")
            raise

    async def list_folders(
        self, parent_id: Optional[str] = None, recursive: bool = False, max_depth: int = 3
    ) -> Dict[str, Any]:
        """List subfolders within a specific parent folder, optionally recursing down the tree.

        If parent_id is not specified, it lists the contents under the Personal folder root.

        Args:
            parent_id: Optional unique identifier of the parent folder.
            recursive: Whether to recursively traverse subfolders.
            max_depth: Maximum depth to traverse if recursive is True (default: 3, max: 5).

        Returns:
            Dict containing a list of subfolders and parent metadata.
        """
        try:
            if not parent_id or not parent_id.strip():
                logger.info("No parent_id specified. Defaulting to Personal folder root.")
                parent_folder = await self.api_client.get_personal_folder_root()
            else:
                logger.info(f"Listing subfolders under parent {parent_id}")
                parent_folder = await self.api_client.get_folder(parent_id.strip())

            # Enforce max depth limit of 5 to protect API performance
            safe_max_depth = min(max(1, max_depth), 5)
            subfolders = []

            async def recurse_folders(current_folder: Dict[str, Any], current_path: str, depth: int):
                if depth > safe_max_depth:
                    return

                children = current_folder.get("children", [])
                for child in children:
                    item_type = (child.get("itemType") or child.get("contentType") or "").lower()
                    if item_type == "folder":
                        child_id = child.get("id")
                        child_name = child.get("name") or child.get("title", "")
                        child_path = f"{current_path}/{child_name}"

                        folder_record = {
                            "id": child_id,
                            "name": child_name,
                            "path": child_path,
                            "description": child.get("description", ""),
                            "created_at": child.get("createdAt"),
                            "created_by": child.get("createdBy"),
                            "modified_at": child.get("modifiedAt"),
                            "modified_by": child.get("modifiedBy"),
                            "parent_id": current_folder.get("id"),
                            "depth": depth
                        }
                        subfolders.append(folder_record)

                        if recursive:
                            try:
                                nested_folder = await self.api_client.get_folder(child_id)
                                await recurse_folders(nested_folder, child_path, depth + 1)
                            except Exception as e:
                                logger.warning(
                                    f"Failed to fetch subfolder {child_name} ({child_id}) during recursion: {e}"
                                )

            parent_name = parent_folder.get("name") or parent_folder.get("title", "Root")
            await recurse_folders(parent_folder, f"/{parent_name}", 1)

            return {
                "parent_folder_id": parent_folder.get("id"),
                "parent_folder_name": parent_name,
                "recursive_applied": recursive,
                "max_depth_applied": safe_max_depth,
                "subfolders": subfolders,
                "total_count": len(subfolders),
            }

        except APIError as e:
            logger.error(f"Failed to list subfolders: {e}")
            raise

    async def get_folder_by_path(self, path: str) -> Dict[str, Any]:
        """Resolve a slash-separated path (e.g. '/Personal/MyFolder/SubFolder') to a folder.

        Args:
            path: Slash-separated folder path. First segment must be 'Personal' or 'Global'/'Shared'.

        Returns:
            Dict containing folder configuration and contents.
        """
        try:
            # Clean and parse the path
            clean_path = path.strip().strip("/")
            if not clean_path:
                raise ValidationError("Path must be a non-empty string")

            segments = clean_path.split("/")
            root_segment = segments[0].lower()

            logger.info(f"Resolving folder path: {path}")

            # Resolve root folder
            if root_segment == "personal":
                current_folder = await self.api_client.get_personal_folder_root()
            elif root_segment in ["global", "shared"]:
                current_folder = await self.api_client.get_global_folder_root()
            else:
                # Default fallback to personal root
                logger.warning(
                    f"Root segment '{segments[0]}' not recognized. Defaulting to 'Personal'."
                )
                current_folder = await self.api_client.get_personal_folder_root()
                # If segment[0] is just a folder name under personal root, don't consume it as the root specifier
                # We start traversal from personal root, but we include segments[0] as a child folder to resolve
                segments = ["personal"] + segments

            # Traverse down the subfolder path
            for segment in segments[1:]:
                children = current_folder.get("children", [])
                found_child = None
                for child in children:
                    item_type = (child.get("itemType") or child.get("contentType") or "").lower()
                    item_name = (child.get("name") or child.get("title") or "").lower()
                    if item_type == "folder" and item_name == segment.lower():
                        found_child = child
                        break

                if not found_child:
                    raise ValidationError(
                        f"Subfolder '{segment}' not found in parent path. Available folders: "
                        f"{[c.get('name') or c.get('title') for c in children if (c.get('itemType') or c.get('contentType') or '').lower() == 'folder']}"
                    )

                # Fetch child folder's full details (with its own children)
                current_folder = await self.api_client.get_folder(found_child["id"])

            return current_folder

        except ValidationError as e:
            logger.error(f"Path resolution validation failed: {e}")
            raise
        except APIError as e:
            logger.error(f"Path resolution API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error resolving path: {e}")
            raise APIError(f"Path resolution failed: {str(e)}")

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for folder operations.

        Returns:
            List of tool definitions for MCP server registration.
        """
        return [
            {
                "name": "list_folders",
                "description": "List all subfolders under a parent folder, optionally traversing recursively.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "parent_id": {
                            "type": "string",
                            "description": "Optional ID of the parent folder to list subfolders from",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "True to recursively traverse subfolders (default: false)",
                            "default": False,
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum recursion depth to traverse if recursive is True (default: 3, max: 5)",
                            "minimum": 1,
                            "maximum": 5,
                            "default": 3,
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_personal_folder_root",
                "description": "Retrieve the root of the user's personal content folder",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_global_folder_root",
                "description": "Retrieve the root of the organization's global content folder",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_folder",
                "description": "Retrieve a specific folder configuration and its child items by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Unique identifier of the folder",
                        }
                    },
                    "required": ["folder_id"],
                },
            },
            {
                "name": "create_folder",
                "description": "Create a new folder in the content library",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the new folder (max 255 characters)",
                        },
                        "parent_id": {
                            "type": "string",
                            "description": "ID of the parent folder where this folder will reside",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional folder description",
                        },
                    },
                    "required": ["name", "parent_id"],
                },
            },
            {
                "name": "delete_folder",
                "description": "Delete a folder or other library content item",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Unique identifier of the folder or content item to delete",
                        },
                        "wait_for_completion": {
                            "type": "boolean",
                            "description": "Wait for deletion job to finish before returning (default: true)",
                            "default": True,
                        },
                    },
                    "required": ["folder_id"],
                },
            },
            {
                "name": "get_folder_by_path",
                "description": (
                    "Resolve a slash-separated path (e.g. '/Personal/MyFolder/SubFolder') to "
                    "retrieve a folder's ID, metadata, and contents"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Slash-separated path. First segment must be 'Personal' or "
                                "'Global'/'Shared' (e.g., '/Personal/Production/Alerts')"
                            ),
                        }
                    },
                    "required": ["path"],
                },
            },
        ]
