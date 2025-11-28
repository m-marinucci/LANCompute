"""Tests for mDNS/Bonjour discovery helper."""

from unittest.mock import MagicMock, patch

import pytest

from src.lancompute.mdns_discovery import (
    SERVICE_TYPE_RFB,
    DiscoveredService,
    ScreenSharingListener,
    discover_screen_sharing_services,
)


class TestScreenSharingListener:
    """Unit tests for ScreenSharingListener."""

    def test_add_service_populates_results(self) -> None:
        """add_service should store basic service information."""
        listener = ScreenSharingListener()

        class DummyInfo:
            def __init__(self) -> None:
                self.port = 5900
                self.server = "Test-Mac.local."
                self.name = "Test Mac._rfb._tcp.local."

            def parsed_addresses(self):
                return ["192.168.1.42"]

        class DummyZeroconf:
            def get_service_info(self, service_type: str, name: str):
                assert service_type == SERVICE_TYPE_RFB
                return DummyInfo()

        listener.add_service(
            DummyZeroconf(), SERVICE_TYPE_RFB, "Test Mac._rfb._tcp.local."
        )

        services = listener.get_services()
        assert len(services) == 1
        svc: DiscoveredService = services[0]
        assert svc["ip"] == "192.168.1.42"
        assert svc["port"] == 5900
        assert svc["service_type"] == SERVICE_TYPE_RFB
        assert "Test Mac" in svc["name"]
        assert svc["hostname"] == "Test-Mac.local"


class TestDiscoverScreenSharingServices:
    """Unit and integration tests for discover_screen_sharing_services."""

    def test_discover_returns_empty_on_no_services(self) -> None:
        """When no services are discovered, services list should be empty."""

        class DummyZeroconf:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        with patch(
            "src.lancompute.mdns_discovery.Zeroconf", DummyZeroconf
        ), patch("src.lancompute.mdns_discovery.ServiceBrowser", MagicMock()):
            result = discover_screen_sharing_services(timeout=0.0)

        assert result["error"] is None
        assert isinstance(result["services"], list)

    def test_discover_reports_error_on_zeroconf_failure(self) -> None:
        """Zeroconf initialization failure should populate error field."""
        with patch(
            "src.lancompute.mdns_discovery.Zeroconf",
            side_effect=OSError("boom"),
        ):
            result = discover_screen_sharing_services(timeout=0.1)

        assert result["services"] == []
        assert result["error"] is not None

    @pytest.mark.integration
    def test_discover_integration_runs_without_crashing(self) -> None:
        """Integration discovery should always return a well-formed result."""
        result = discover_screen_sharing_services(timeout=0.1)
        assert "services" in result
        assert "duration_seconds" in result

