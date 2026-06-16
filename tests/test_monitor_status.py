"""Unit tests for monitor status normalization in the API client.

These tests exercise the pure helper methods added for get_monitor_status
without requiring live credentials or network access. The client instance is
created with object.__new__ to bypass __init__, since the helpers only rely on
the class-level _TRIGGER_SEVERITY_ORDER attribute.
"""

import pytest

from sumologic_mcp.api_client import SumoLogicAPIClient


@pytest.fixture
def client() -> SumoLogicAPIClient:
    """Return an API client instance without running __init__."""
    return object.__new__(SumoLogicAPIClient)


class TestUnwrapMonitorItem:
    def test_unwraps_search_result_element(self, client):
        element = {"item": {"id": "1", "name": "cpu"}, "path": "/Monitors/cpu"}
        assert client._unwrap_monitor_item(element) == {"id": "1", "name": "cpu"}

    def test_returns_flat_monitor_unchanged(self, client):
        monitor = {"id": "1", "name": "cpu"}
        assert client._unwrap_monitor_item(monitor) == monitor

    def test_handles_non_dict_item(self, client):
        element = {"item": "not-a-dict"}
        assert client._unwrap_monitor_item(element) == element


class TestNormalizeMonitorStatus:
    def test_disabled_flag_wins(self, client):
        assert client._normalize_monitor_status(True, ["Critical"]) == ("Disabled", None)

    def test_disabled_status_string(self, client):
        assert client._normalize_monitor_status(False, ["Disabled"]) == ("Disabled", None)

    def test_normal(self, client):
        assert client._normalize_monitor_status(False, ["Normal"]) == ("Normal", None)

    def test_triggered_critical(self, client):
        assert client._normalize_monitor_status(False, ["Critical"]) == (
            "Triggered",
            "Critical",
        )

    def test_severity_ordering_prefers_critical(self, client):
        status, severity = client._normalize_monitor_status(
            False, ["MissingData", "Warning", "Critical"]
        )
        assert status == "Triggered"
        assert severity == "Critical"

    def test_severity_ordering_prefers_warning_over_missing_data(self, client):
        status, severity = client._normalize_monitor_status(
            False, ["MissingData", "Warning"]
        )
        assert status == "Triggered"
        assert severity == "Warning"

    def test_unknown_severity_still_triggered(self, client):
        status, severity = client._normalize_monitor_status(False, ["SomethingElse"])
        assert status == "Triggered"
        assert severity == "SomethingElse"

    def test_empty_status_is_unknown(self, client):
        assert client._normalize_monitor_status(False, []) == ("Unknown", None)

    def test_none_status_is_unknown(self, client):
        assert client._normalize_monitor_status(False, None) == ("Unknown", None)


class TestBuildMonitorStatusRecord:
    def test_maps_core_fields_and_nulls_timing(self, client):
        monitor = {
            "id": "0000000000ABCDEF",
            "name": "High CPU",
            "isDisabled": False,
            "status": ["Critical"],
            "monitorType": "Logs",
        }

        record = client._build_monitor_status_record(monitor)

        assert record["monitorId"] == "0000000000ABCDEF"
        assert record["monitorName"] == "High CPU"
        assert record["status"] == "Triggered"
        assert record["currentTriggerSeverity"] == "Critical"
        assert record["isDisabled"] is False
        assert record["rawStatus"] == ["Critical"]
        assert record["monitorType"] == "Logs"
        # Timing fields are unavailable from the Monitors Management API.
        assert record["lastTriggered"] is None
        assert record["triggerCount24h"] == 0
        assert record["lastEvaluation"] is None
        assert record["nextEvaluation"] is None

    def test_disabled_monitor(self, client):
        monitor = {"id": "1", "name": "x", "isDisabled": True, "status": ["Normal"]}
        record = client._build_monitor_status_record(monitor)
        assert record["status"] == "Disabled"
        assert record["currentTriggerSeverity"] is None

    def test_missing_name_defaults_to_unknown(self, client):
        record = client._build_monitor_status_record({"id": "1", "status": ["Normal"]})
        assert record["monitorName"] == "Unknown"
        assert record["status"] == "Normal"
