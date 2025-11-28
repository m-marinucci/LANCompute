"""mDNS/Bonjour discovery for screen sharing services."""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional, TypedDict

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf


logger = logging.getLogger(__name__)


SERVICE_TYPE_RFB = "_rfb._tcp.local."
SERVICE_TYPE_SCREENSHARING = "_screensharing._tcp.local."
SCREEN_SHARING_SERVICE_TYPES = [
    SERVICE_TYPE_RFB,
    SERVICE_TYPE_SCREENSHARING,
]


class DiscoveredService(TypedDict):
    """Single service discovered via mDNS/Bonjour."""

    name: str
    ip: str
    port: int
    service_type: str
    hostname: str


class DiscoveryResult(TypedDict):
    """Result from discover_screen_sharing_services()."""

    services: List[DiscoveredService]
    duration_seconds: float
    error: Optional[str]


class ScreenSharingListener(ServiceListener):
    """Collect screen sharing services discovered via zeroconf."""

    def __init__(self) -> None:
        self._services: List[DiscoveredService] = []
        self._lock = threading.Lock()

    def add_service(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:  # type: ignore[override]
        info = zeroconf.get_service_info(service_type, name)
        if not info:
            return
        self._add_or_update(info, service_type)

    def update_service(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:  # type: ignore[override]
        info = zeroconf.get_service_info(service_type, name)
        if not info:
            return
        self._add_or_update(info, service_type)

    def remove_service(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:  # type: ignore[override]
        # We only care about currently visible services; removals are ignored.
        logger.debug("Service removed: %s (%s)", name, service_type)

    def _add_or_update(self, info: ServiceInfo, service_type: str) -> None:
        addresses = info.parsed_addresses()
        if not addresses:
            return

        ip = addresses[0]
        hostname = info.server.rstrip(".") if info.server else ""
        name = info.name.rstrip(".") if info.name else hostname or ip

        service: DiscoveredService = {
            "name": name,
            "ip": ip,
            "port": info.port,
            "service_type": service_type,
            "hostname": hostname,
        }

        with self._lock:
            self._services.append(service)

    def get_services(self) -> List[DiscoveredService]:
        """Return a snapshot of discovered services."""
        with self._lock:
            return list(self._services)


def discover_screen_sharing_services(
    timeout: float = 5.0,
) -> DiscoveryResult:
    """Synchronously discover screen sharing services via mDNS/Bonjour."""
    start = time.perf_counter()

    try:
        zeroconf = Zeroconf()
    except Exception as exc:  # pragma: no cover - exercised via unit tests
        duration = time.perf_counter() - start
        message = f"zeroconf initialization failed: {exc}"
        logger.warning("mDNS discovery unavailable: %s", message)
        return {
            "services": [],
            "duration_seconds": duration,
            "error": message,
        }

    listener = ScreenSharingListener()

    try:
        browsers: List[ServiceBrowser] = []
        for service_type in SCREEN_SHARING_SERVICE_TYPES:
            browsers.append(ServiceBrowser(zeroconf, service_type, listener))

        # Block for the requested timeout while zeroconf collects services.
        time.sleep(max(timeout, 0.0))

        services = listener.get_services()
        duration = time.perf_counter() - start
        return {
            "services": services,
            "duration_seconds": duration,
            "error": None,
        }
    except Exception as exc:
        duration = time.perf_counter() - start
        message = f"mDNS discovery failed: {exc}"
        logger.warning("mDNS discovery failed: %s", exc)
        return {
            "services": [],
            "duration_seconds": duration,
            "error": message,
        }
    finally:
        try:
            zeroconf.close()
        except Exception:
            # Best-effort cleanup only.
            logger.debug("Failed to close Zeroconf instance", exc_info=True)

