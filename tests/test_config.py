import pytest
from pydantic import ValidationError

from sumologic_mcp.config import SumoLogicConfig


class TestConfigEndpointValidation:
    def test_valid_standard_endpoint(self):
        config = SumoLogicConfig(
            access_id="test_id",
            access_key="test_key",
            endpoint="https://api.sumologic.com",
        )
        assert config.endpoint == "https://api.sumologic.com"

    def test_endpoint_with_trailing_slash(self):
        config = SumoLogicConfig(
            access_id="test_id",
            access_key="test_key",
            endpoint="https://api.sumologic.com/",
        )
        assert config.endpoint == "https://api.sumologic.com"

    def test_endpoint_with_api_suffix(self):
        config = SumoLogicConfig(
            access_id="test_id",
            access_key="test_key",
            endpoint="https://api.sumologic.com/api",
        )
        assert config.endpoint == "https://api.sumologic.com"

    def test_endpoint_with_api_v1_suffix(self):
        config = SumoLogicConfig(
            access_id="test_id",
            access_key="test_key",
            endpoint="https://api.us2.sumologic.com/api/v1/",
        )
        assert config.endpoint == "https://api.us2.sumologic.com"

    def test_invalid_protocol(self):
        with pytest.raises(ValidationError) as excinfo:
            SumoLogicConfig(
                access_id="test_id",
                access_key="test_key",
                endpoint="ftp://api.sumologic.com",
            )
        assert "Endpoint must be a valid HTTP/HTTPS URL" in str(excinfo.value)

    def test_invalid_domain(self):
        with pytest.raises(ValidationError) as excinfo:
            SumoLogicConfig(
                access_id="test_id",
                access_key="test_key",
                endpoint="https://api.example.com",
            )
        assert "Endpoint must be a valid Sumo Logic domain" in str(excinfo.value)
