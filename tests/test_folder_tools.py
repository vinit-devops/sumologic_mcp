"""Unit tests for FolderTools class and folder management MCP tools."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from datetime import datetime

from sumologic_mcp.api_client import SumoLogicAPIClient
from sumologic_mcp.exceptions import ValidationError, APIError
from sumologic_mcp.tools.folder_tools import FolderTools


@pytest.fixture
def mock_api_client():
    client = MagicMock(spec=SumoLogicAPIClient)
    client.get_personal_folder_root = AsyncMock()
    client.get_global_folder_root = AsyncMock()
    client.get_folder = AsyncMock()
    client.create_folder = AsyncMock()
    client.delete_folder_job = AsyncMock()
    client.get_delete_folder_status = AsyncMock()
    return client


class TestFolderTools:
    @pytest.mark.asyncio
    async def test_get_personal_folder_root(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_response = {"id": "personal_root", "name": "Personal", "children": []}
        mock_api_client.get_personal_folder_root.return_value = mock_response

        result = await tools.get_personal_folder_root()
        assert result == mock_response
        mock_api_client.get_personal_folder_root.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_global_folder_root(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_response = {"id": "global_root", "name": "Global", "children": []}
        mock_api_client.get_global_folder_root.return_value = mock_response

        result = await tools.get_global_folder_root()
        assert result == mock_response
        mock_api_client.get_global_folder_root.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_folder(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_response = {"id": "folder123", "name": "My Folder", "children": []}
        mock_api_client.get_folder.return_value = mock_response

        result = await tools.get_folder("folder123")
        assert result == mock_response
        mock_api_client.get_folder.assert_called_once_with("folder123")

    @pytest.mark.asyncio
    async def test_create_folder(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_response = {"id": "new_folder", "name": "Sub", "parentId": "parent123"}
        mock_api_client.create_folder.return_value = mock_response

        result = await tools.create_folder("Sub", "parent123", "Desc")
        assert result == mock_response
        mock_api_client.create_folder.assert_called_once_with(
            name="Sub", parent_id="parent123", description="Desc"
        )

    @pytest.mark.asyncio
    async def test_delete_folder_no_wait(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_api_client.delete_folder_job.return_value = {"id": "job123"}

        result = await tools.delete_folder("folder123", wait_for_completion=False)
        assert result["status"] == "InProgress"
        assert result["job_id"] == "job123"
        mock_api_client.delete_folder_job.assert_called_once_with("folder123")
        mock_api_client.get_delete_folder_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_folder_wait_success(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_api_client.delete_folder_job.return_value = {"id": "job123"}
        mock_api_client.get_delete_folder_status.side_effect = [
            {"status": "InProgress"},
            {"status": "Success"},
        ]

        result = await tools.delete_folder("folder123", wait_for_completion=True)
        assert result["status"] == "Success"
        assert result["job_id"] == "job123"
        assert mock_api_client.get_delete_folder_status.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_folder_wait_failed(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_api_client.delete_folder_job.return_value = {"id": "job123"}
        mock_api_client.get_delete_folder_status.return_value = {
            "status": "Failed",
            "error": {"message": "Permission denied"},
        }

        with pytest.raises(APIError) as excinfo:
            await tools.delete_folder("folder123", wait_for_completion=True)
        
        assert "Folder deletion job failed: Permission denied" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_list_folders_default(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        personal_root = {
            "id": "personal_root",
            "name": "Personal",
            "children": [
                {"id": "sub1", "name": "Analytics", "itemType": "Folder"},
                {"id": "dash1", "title": "Dashboard", "itemType": "Dashboard"},
            ],
        }
        mock_api_client.get_personal_folder_root.return_value = personal_root

        result = await tools.list_folders()
        assert result["parent_folder_id"] == "personal_root"
        assert len(result["subfolders"]) == 1
        assert result["subfolders"][0]["id"] == "sub1"
        assert result["subfolders"][0]["name"] == "Analytics"
        mock_api_client.get_personal_folder_root.assert_called_once()
        mock_api_client.get_folder.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_folders_with_id(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        mock_folder = {
            "id": "folder123",
            "name": "My Folder",
            "children": [
                {"id": "sub2", "name": "Production", "contentType": "Folder"},
            ],
        }
        mock_api_client.get_folder.return_value = mock_folder

        result = await tools.list_folders("folder123")
        assert result["parent_folder_id"] == "folder123"
        assert len(result["subfolders"]) == 1
        assert result["subfolders"][0]["id"] == "sub2"
        mock_api_client.get_folder.assert_called_once_with("folder123")

    @pytest.mark.asyncio
    async def test_list_folders_recursive(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        personal_root = {
            "id": "personal_root",
            "name": "Personal",
            "children": [
                {"id": "sub1", "name": "Analytics", "itemType": "Folder"},
            ],
        }
        analytics_folder = {
            "id": "sub1",
            "name": "Analytics",
            "children": [
                {"id": "sub2", "name": "Production", "itemType": "Folder"}
            ],
        }
        prod_folder = {
            "id": "sub2",
            "name": "Production",
            "children": [],
        }

        mock_api_client.get_personal_folder_root.return_value = personal_root
        mock_api_client.get_folder.side_effect = [analytics_folder, prod_folder]

        result = await tools.list_folders(recursive=True)
        assert result["parent_folder_id"] == "personal_root"
        assert result["recursive_applied"] is True
        assert len(result["subfolders"]) == 2
        
        # Verify first level child
        assert result["subfolders"][0]["id"] == "sub1"
        assert result["subfolders"][0]["path"] == "/Personal/Analytics"
        assert result["subfolders"][0]["depth"] == 1
        
        # Verify nested child
        assert result["subfolders"][1]["id"] == "sub2"
        assert result["subfolders"][1]["path"] == "/Personal/Analytics/Production"
        assert result["subfolders"][1]["depth"] == 2

        mock_api_client.get_personal_folder_root.assert_called_once()
        mock_api_client.get_folder.assert_any_call("sub1")
        mock_api_client.get_folder.assert_any_call("sub2")

    @pytest.mark.asyncio
    async def test_get_folder_by_path_personal(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        personal_root = {
            "id": "personal_root",
            "name": "Personal",
            "children": [
                {"id": "sub1", "name": "Analytics", "itemType": "Folder"},
                {"id": "dash1", "title": "Dashboard", "itemType": "Dashboard"},
            ],
        }
        analytics_folder = {
            "id": "sub1",
            "name": "Analytics",
            "children": [
                {"id": "sub2", "name": "Production", "contentType": "Folder"}
            ],
        }
        prod_folder = {
            "id": "sub2",
            "name": "Production",
            "children": [],
        }

        mock_api_client.get_personal_folder_root.return_value = personal_root
        mock_api_client.get_folder.side_effect = [analytics_folder, prod_folder]

        result = await tools.get_folder_by_path("/Personal/Analytics/Production")
        assert result == prod_folder
        mock_api_client.get_personal_folder_root.assert_called_once()
        mock_api_client.get_folder.assert_any_call("sub1")
        mock_api_client.get_folder.assert_any_call("sub2")

    @pytest.mark.asyncio
    async def test_get_folder_by_path_not_found(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        personal_root = {
            "id": "personal_root",
            "name": "Personal",
            "children": [
                {"id": "sub1", "name": "Analytics", "itemType": "Folder"},
            ],
        }
        mock_api_client.get_personal_folder_root.return_value = personal_root

        with pytest.raises(ValidationError) as excinfo:
            await tools.get_folder_by_path("/Personal/MissingFolder")

        assert "Subfolder 'MissingFolder' not found" in str(excinfo.value)

    def test_get_tool_definitions(self, mock_api_client):
        tools = FolderTools(mock_api_client)
        defs = tools.get_tool_definitions()

        assert len(defs) == 7
        names = [d["name"] for d in defs]
        assert "list_folders" in names
        assert "get_personal_folder_root" in names
        assert "get_global_folder_root" in names
        assert "get_folder" in names
        assert "create_folder" in names
        assert "delete_folder" in names
        assert "get_folder_by_path" in names
