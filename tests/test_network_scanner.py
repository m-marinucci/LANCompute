"""Tests for network_scanner module."""
import pytest
from unittest.mock import patch, MagicMock
import socket
import ipaddress
from src.lancompute.network_scanner import (
    ping_host, scan_port, get_local_network, scan_host
)


class TestNetworkScanner:
    """Test cases for network scanner functionality."""
    
    def test_ping_host_success(self):
        """Test successful ping."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            result = ping_host("127.0.0.1")
            assert result is True
    
    def test_ping_host_failure(self):
        """Test failed ping."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 1
            result = ping_host("192.168.999.999")
            assert result is False
    
    def test_scan_port_returns_boolean(self):
        """Test that scan_port returns banner string for open ports."""
        with patch('socket.socket') as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 0
            mock_sock.recv.return_value = b"HTTP/1.1 200 OK"

            result = scan_port("127.0.0.1", 80)
            # scan_port returns banner string for open ports
            assert result == "HTTP/1.1 200 OK"

    def test_scan_port_open_no_banner_returns_open(self):
        """Test that scan_port returns 'Open' when port is open but no banner is received."""
        with patch('socket.socket') as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 0
            mock_sock.recv.return_value = b""

            result = scan_port("127.0.0.1", 80)
            assert result == "Open"
    
    def test_scan_port_closed_returns_none(self):
        """Test scanning a closed port returns None."""
        with patch('socket.socket') as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 1

            result = scan_port("127.0.0.1", 9999)
            assert result is None
    
    def test_get_local_network_fallback(self):
        """Test getting local network with fallback."""
        # Test the actual function behavior - it may return current network
        result = get_local_network()
        # Should return a valid CIDR network
        assert "/" in result
        assert len(result.split(".")) >= 3
    
    def test_scan_host_basic(self):
        """Test basic host scanning functionality."""
        with patch('src.lancompute.network_scanner.ping_host', return_value=True):
            with patch('src.lancompute.network_scanner.scan_port', return_value=None):
                result = scan_host("127.0.0.1", [80, 8080])

                assert result['ip'] == "127.0.0.1"
                assert result['alive'] is True
                assert isinstance(result['open_ports'], list)
                assert isinstance(result['services'], dict)
