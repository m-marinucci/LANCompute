"""Tests for network_scanner module."""

from unittest.mock import MagicMock, patch

import pytest

from src.lancompute.network_scanner import (
    diagnose_host,
    get_local_network,
    ping_host,
    scan_host,
    scan_port,
)


class TestNetworkScanner:
    """Test cases for basic network scanner functionality."""

    def test_ping_host_success(self) -> None:
        """Test successful ping."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = ping_host("127.0.0.1")
            assert result is True

    def test_ping_host_failure(self) -> None:
        """Test failed ping."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            result = ping_host("192.168.999.999")
            assert result is False

    def test_scan_port_returns_banner_string(self) -> None:
        """scan_port should return banner string for open ports."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 0
            mock_sock.recv.return_value = b"HTTP/1.1 200 OK"

            result = scan_port("127.0.0.1", 80)
            assert result == "HTTP/1.1 200 OK"

    def test_scan_port_open_no_banner_returns_open(self) -> None:
        """scan_port should return 'Open' when port is open but no banner is received."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 0
            mock_sock.recv.return_value = b""

            result = scan_port("127.0.0.1", 80)
            assert result == "Open"

    def test_scan_port_closed_returns_none(self) -> None:
        """Scanning a closed port should return None."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 1

            result = scan_port("127.0.0.1", 9999)
            assert result is None

    def test_get_local_network_fallback(self) -> None:
        """Test getting local network with fallback."""
        result = get_local_network()
        # Should return a valid CIDR network
        assert "/" in result
        assert len(result.split(".")) >= 3

    def test_scan_host_basic(self) -> None:
        """Test basic host scanning functionality."""
        with patch("src.lancompute.network_scanner.ping_host", return_value=True):
            with patch(
                "src.lancompute.network_scanner.scan_port", return_value=None
            ):
                result = scan_host("127.0.0.1", [80, 8080])

                assert result["ip"] == "127.0.0.1"
                assert result["alive"] is True
                assert isinstance(result["open_ports"], list)
                assert isinstance(result["services"], dict)


class TestDiagnoseHost:
    """Unit tests for diagnostic mode."""

    def test_diagnose_host_reachable_vnc_open(self) -> None:
        """If VNC is open and ping succeeds, status should be reachable."""
        with patch(
            "src.lancompute.network_scanner.subprocess.run"
        ) as mock_run, patch(
            "src.lancompute.network_scanner._check_port"
        ) as mock_check:
            # Ping success
            mock_run.return_value.returncode = 0

            # VNC open, ARD closed, SSH open
            mock_check.side_effect = [
                {
                    "port": 5900,
                    "name": "VNC",
                    "status": "open",
                    "banner": "RFB 003.008",
                    "response_ms": 5.0,
                },
                {
                    "port": 3283,
                    "name": "ARD",
                    "status": "closed",
                    "banner": None,
                    "response_ms": 5.0,
                },
                {
                    "port": 22,
                    "name": "SSH",
                    "status": "open",
                    "banner": "SSH-2.0-OpenSSH_9.0",
                    "response_ms": 5.0,
                },
            ]

            report = diagnose_host("127.0.0.1")

        assert report["overall_status"] == "reachable"
        assert report["resolved_ip"] == "127.0.0.1"
        assert report["ping"]["success"] is True
        assert any(p["name"] == "VNC" and p["status"] == "open" for p in report["ports"])

    def test_diagnose_host_unreachable(self) -> None:
        """If ping fails, overall status should be unreachable and ports skipped."""
        with patch(
            "src.lancompute.network_scanner.subprocess.run"
        ) as mock_run, patch(
            "src.lancompute.network_scanner._check_port"
        ) as mock_check:
            mock_run.return_value.returncode = 1  # host unreachable

            report = diagnose_host("127.0.0.1")

        assert report["overall_status"] == "unreachable"
        assert all(p["status"] == "skipped" for p in report["ports"])
        assert any("Verify the host is powered on" in r for r in report["recommendations"])

    def test_diagnose_host_partial_connectivity(self) -> None:
        """If VNC/ARD are closed but SSH is open, status should be partial."""
        with patch(
            "src.lancompute.network_scanner.subprocess.run"
        ) as mock_run, patch(
            "src.lancompute.network_scanner._check_port"
        ) as mock_check:
            mock_run.return_value.returncode = 0  # ping success

            mock_check.side_effect = [
                {
                    "port": 5900,
                    "name": "VNC",
                    "status": "closed",
                    "banner": None,
                    "response_ms": 5.0,
                },
                {
                    "port": 3283,
                    "name": "ARD",
                    "status": "closed",
                    "banner": None,
                    "response_ms": 5.0,
                },
                {
                    "port": 22,
                    "name": "SSH",
                    "status": "open",
                    "banner": "SSH-2.0-OpenSSH_9.0",
                    "response_ms": 5.0,
                },
            ]

            report = diagnose_host("127.0.0.1")

        assert report["overall_status"] == "partial"
        assert any(p["name"] == "SSH" and p["status"] == "open" for p in report["ports"])

    def test_diagnose_host_resolution_failure(self) -> None:
        """Invalid hostname should set resolution_error and skip further checks."""
        with patch("src.lancompute.network_scanner.ipaddress.ip_address") as mock_ip, patch(
            "src.lancompute.network_scanner.socket.gethostbyname"
        ) as mock_gethost:
            mock_ip.side_effect = ValueError("not an IP")
            mock_gethost.side_effect = OSError("name resolution failed")

            report = diagnose_host("invalid.hostname.example")

        assert report["resolved_ip"] is None
        assert report["resolution_error"] is not None
        assert report["overall_status"] == "error"
