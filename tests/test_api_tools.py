"""Unit tests for the APITools class and execute_raw_request method."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sumologic_mcp.api_client import SumoLogicAPIClient
from sumologic_mcp.exceptions import ValidationError
from sumologic_mcp.tools.api_tools import APITools


@pytest.fixture
def mock_api_client():
    client = MagicMock(spec=SumoLogicAPIClient)
    client.execute_raw_request = AsyncMock()
    return client


class TestAPITools:
    @pytest.mark.asyncio
    async def test_api_call_valid_get(self, mock_api_client):
        tools = APITools(mock_api_client)

        mock_response = {
            "status_code": 200,
            "headers": {"content-type": "application/json"},
            "body": {"status": "ok"},
        }
        mock_api_client.execute_raw_request.return_value = mock_response

        result = await tools.api_call(
            method="GET",
            path="/v1/users",
            params={"limit": 5},
            headers={"Custom-Header": "value"},
        )

        assert result == mock_response
        mock_api_client.execute_raw_request.assert_called_once_with(
            method="GET",
            path="/v1/users",
            params={"limit": 5},
            body=None,
            headers={"Custom-Header": "value"},
        )

    @pytest.mark.asyncio
    async def test_api_call_invalid_method(self, mock_api_client):
        tools = APITools(mock_api_client)

        with pytest.raises(ValidationError) as excinfo:
            await tools.api_call(method="INVALID", path="/v1/users")

        assert "Method must be one of" in str(excinfo.value)
        mock_api_client.execute_raw_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_call_empty_path(self, mock_api_client):
        tools = APITools(mock_api_client)

        with pytest.raises(ValidationError) as excinfo:
            await tools.api_call(method="GET", path="")

        assert "Path must be a non-empty string" in str(excinfo.value)
        mock_api_client.execute_raw_request.assert_not_called()

    def test_get_tool_definitions(self, mock_api_client):
        tools = APITools(mock_api_client)
        defs = tools.get_tool_definitions()

        assert len(defs) == 1
        assert defs[0]["name"] == "api_call"
        assert "method" in defs[0]["inputSchema"]["properties"]
        assert "path" in defs[0]["inputSchema"]["properties"]
