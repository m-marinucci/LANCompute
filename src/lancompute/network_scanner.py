#!/usr/bin/env python3
"""
Network scanner to discover machines suitable for running LLM processes and
screen sharing services (VNC, Apple Remote Desktop).
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Sequence, TypedDict, Union

from ipaddress import IPv4Address, IPv6Address

from .mdns_discovery import (
    DiscoveredService,
    DiscoveryResult,
    discover_screen_sharing_services,
)

# Common HTTP-like ports where a simple GET may elicit a banner
HTTP_PORTS = [1234, 8080, 5000, 8000, 3000]


class PingResult(TypedDict):
    """Result of ping check."""

    success: bool
    response_ms: Optional[float]
    error: Optional[str]


class PortCheck(TypedDict):
    """Result of checking a single port."""

    port: int
    name: str
    status: str
    banner: Optional[str]
    response_ms: Optional[float]


class DiagnosticReport(TypedDict):
    """Result from diagnose_host()."""

    target: str
    resolved_ip: Optional[str]
    resolution_error: Optional[str]
    ping: PingResult
    ports: List[PortCheck]
    recommendations: List[str]
    overall_status: str


class HostInfo(TypedDict, total=False):
    """Extended host information including identified services."""

    ip: str
    alive: bool
    open_ports: List[int]
    services: Dict[int, str]
    identified_services: List[str]


def get_local_network() -> str:
    """Get the local network subnet."""
    try:
        # Get local IP address
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # For macOS/Linux, get more accurate network info
        if platform.system() != "Windows":
            if platform.system() == "Darwin":
                cmd = ["ifconfig"]
            else:
                cmd = ["ip", "addr"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Simple heuristic: find IP that starts with common private ranges
            for line in result.stdout.split('\n'):
                if 'inet ' in line and not '127.0.0.1' in line:
                    parts = line.strip().split()
                    for part in parts:
                        if '.' in part and not 'inet' in part:
                            try:
                                ip = part.split('/')[0]
                                if ip.startswith(('192.168.', '10.', '172.')):
                                    local_ip = ip
                                    break
                            except Exception:
                                continue
        
        # Convert to network subnet
        ip_parts = local_ip.split('.')
        network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
        return network
    except Exception as e:
        logging.warning("Error detecting network: %s", e)
        return "192.168.1.0/24"  # Default fallback


def ping_host(ip: str) -> bool:
    """Check if a host is reachable via ping."""
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", "-W", "1", str(ip)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False


def scan_port(ip: str, port: int, timeout: float = 1.0) -> Optional[str]:
    """Check if a specific port is open on a host and return banner if available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((str(ip), port))

            if result == 0:
                # Port is open, try to get banner
                try:
                    # Send HTTP request for common web services
                    if port in HTTP_PORTS:
                        sock.send(b"GET / HTTP/1.0\r\n\r\n")
                    banner = sock.recv(1024).decode("utf-8", errors="ignore").strip()
                    return banner if banner else "Open"
                except Exception as e:
                    logging.debug("Banner read failed for %s:%s: %s", ip, port, e)
                    return "Open"
            else:
                return None
    except Exception as e:
        logging.debug("scan_port exception for %s:%s: %s", ip, port, e)
        return None


def get_service_banner(ip: str, port: int, timeout: float = 2.0) -> str:
    """Try to get service banner from open port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((str(ip), port))
        
        # Send HTTP request for common web services
        if port in HTTP_PORTS:
            sock.send(b"GET / HTTP/1.0\r\n\r\n")
            banner = sock.recv(1024).decode("utf-8", errors="ignore")
        else:
            banner = sock.recv(1024).decode("utf-8", errors="ignore")
        
        sock.close()
        return banner.strip()
    except Exception as e:
        logging.debug("get_service_banner exception for %s:%s: %s", ip, port, e)
        return ""


def scan_host(
    ip: Union[str, IPv4Address, IPv6Address],
    ports: Sequence[int],
) -> HostInfo:
    """Scan a single host for open ports and services."""
    host_info = {
        "ip": str(ip),
        "alive": False,
        "open_ports": [],
        "services": {},
        "identified_services": [],
    }
    
    # First check if host is alive
    if ping_host(ip):
        host_info["alive"] = True
        
        # Scan specified ports
        for port in ports:
            result = scan_port(ip, port)
            if result:  # Port is open (returns banner string or "Open")
                host_info["open_ports"].append(port)

                # Use the banner from scan_port if available
                if isinstance(result, str) and result != "Open":
                    host_info["services"][port] = result[:100]  # Limit banner length
                else:
                    # Try to get service banner using the old method as fallback
                    banner = get_service_banner(ip, port)
                    if banner:
                        host_info["services"][port] = banner[:100]
    
    return host_info


def _check_port(ip: str, port: int, name: str) -> PortCheck:
    """Check a single port for diagnostic mode."""
    start = time.perf_counter()
    status = "closed"
    banner: Optional[str] = None
    response_ms: Optional[float]

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            result = sock.connect_ex((ip, port))
            response_ms = (time.perf_counter() - start) * 1000.0

            if result == 0:
                status = "open"
                try:
                    if name in ("VNC", "SSH"):
                        data = sock.recv(1024)
                        if data:
                            banner = data.decode("utf-8", errors="ignore").strip()
                except Exception as exc:  # pragma: no cover - debug path
                    logging.debug(
                        "Banner read failed in diagnostic for %s:%s: %s",
                        ip,
                        port,
                        exc,
                    )
            else:
                # Basic classification of closed vs filtered.
                if result in (111, 61, 10061):
                    status = "closed"
                else:
                    status = "filtered"
    except Exception as exc:
        response_ms = (time.perf_counter() - start) * 1000.0
        status = "error"
        banner = str(exc)

    return {
        "port": port,
        "name": name,
        "status": status,
        "banner": banner,
        "response_ms": response_ms,
    }


def diagnose_host(target: str) -> DiagnosticReport:
    """Diagnose connectivity to a single host for screen sharing."""
    report: DiagnosticReport = {
        "target": target,
        "resolved_ip": None,
        "resolution_error": None,
        "ping": {"success": False, "response_ms": None, "error": None},
        "ports": [],
        "recommendations": [],
        "overall_status": "error",
    }

    # Resolve hostname or validate IP.
    try:
        ip_obj = ipaddress.ip_address(target)
        resolved_ip = str(ip_obj)
    except ValueError:
        try:
            resolved_ip = socket.gethostbyname(target)
        except Exception as exc:
            report["resolution_error"] = str(exc)
            report["recommendations"].append(
                "Verify the hostname or IP address and DNS configuration."
            )
            return report

    report["resolved_ip"] = resolved_ip

    # Ping check with basic error classification.
    ping_result: PingResult = {"success": False, "response_ms": None, "error": None}
    start = time.perf_counter()
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", "-W", "1", resolved_ip]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ping_result["response_ms"] = (time.perf_counter() - start) * 1000.0

        if completed.returncode == 0:
            ping_result["success"] = True
        elif completed.returncode == 1:
            ping_result["error"] = "host_unreachable"
        elif completed.returncode == 2:
            ping_result["error"] = "permission_denied"
        else:
            ping_result["error"] = f"error_code_{completed.returncode}"
    except Exception as exc:
        ping_result["response_ms"] = (time.perf_counter() - start) * 1000.0
        ping_result["error"] = str(exc)

    report["ping"] = ping_result

    ports: List[PortCheck] = []

    if ping_result["success"] or ping_result["error"] == "permission_denied":
        if ping_result["error"] == "permission_denied":
            report["recommendations"].append(
                "ICMP ping requires elevated privileges; relying on port checks."
            )

        ports.append(_check_port(resolved_ip, 5900, "VNC"))
        ports.append(_check_port(resolved_ip, 3283, "ARD"))
        ports.append(_check_port(resolved_ip, 22, "SSH"))
    else:
        # Host appears unreachable; record skipped checks.
        for port, name in [(5900, "VNC"), (3283, "ARD"), (22, "SSH")]:
            ports.append(
                {
                    "port": port,
                    "name": name,
                    "status": "skipped",
                    "banner": None,
                    "response_ms": None,
                }
            )

    report["ports"] = ports

    vnc_open = any(
        p["name"] in ("VNC", "ARD") and p["status"] == "open" for p in ports
    )
    ssh_open = any(p["name"] == "SSH" and p["status"] == "open" for p in ports)

    if report["resolution_error"]:
        overall = "error"
    elif not ping_result["success"] and ping_result["error"] != "permission_denied":
        overall = "unreachable"
    elif vnc_open:
        overall = "reachable"
    elif ssh_open:
        overall = "partial"
    else:
        overall = "partial"

    report["overall_status"] = overall

    # Generate recommendations.
    recommendations: List[str] = list(report["recommendations"])
    if overall == "unreachable":
        recommendations.extend(
            [
                "Verify the host is powered on and connected to the network.",
                "Check that you're on the same network/VLAN as the target.",
                f"Confirm the IP address is correct (try: ping {resolved_ip}).",
                "Check if a firewall is blocking ICMP ping requests.",
            ]
        )
    else:
        vnc_port = next((p for p in ports if p["name"] == "VNC"), None)
        ard_port = next((p for p in ports if p["name"] == "ARD"), None)
        ssh_port = next((p for p in ports if p["name"] == "SSH"), None)

        if (vnc_port and vnc_port["status"] != "open") and (
            ard_port and ard_port["status"] != "open"
        ):
            recommendations.extend(
                [
                    "Screen Sharing is not enabled or not reachable on the target.",
                    "On macOS, enable Screen Sharing in "
                    "System Settings > General > Sharing.",
                ]
            )
            if ssh_port and ssh_port["status"] == "open":
                recommendations.extend(
                    [
                        "SSH is available - you can use an SSH tunnel for VNC:",
                        f"  ssh -L 5900:localhost:5900 user@{resolved_ip}",
                        "Then connect to: vnc://localhost:5900",
                    ]
                )
        elif vnc_open:
            recommendations.append(
                "Screen sharing should work; if connection still fails, verify "
                "your user account is allowed in the Screen Sharing settings."
            )

    report["recommendations"] = recommendations

    return report


def _print_diagnostic(report: DiagnosticReport) -> None:
    """Pretty-print a diagnostic report to stdout."""
    print(f"Diagnosing: {report['target']}")
    print("-" * 60)
    print()

    if report["resolution_error"]:
        print("[FAIL] DNS Resolution")
        print(f"    Error: {report['resolution_error']}")
        print()
        print("=" * 60)
        print(f"Overall Status: {report['overall_status'].upper()}")
        if report["recommendations"]:
            print()
            print("Recommendations:")
            for rec in report["recommendations"]:
                print(f"  - {rec}")
        return

    print("[OK] DNS Resolution")
    print(f"    Resolved to: {report['resolved_ip']}")
    print()

    ping = report["ping"]
    if ping["success"]:
        print("[OK] Ping Check")
        print(f"    Host is reachable ({ping['response_ms']:.1f}ms)")
    elif ping["error"] == "permission_denied":
        print("[WARN] Ping Check")
        print("    Permission denied (ICMP requires elevated privileges)")
        print("    Proceeding with port checks...")
    else:
        print("[FAIL] Ping Check")
        print("    Host unreachable")
    print()

    for port in report["ports"]:
        status = port["status"]
        name = port["name"]
        if status == "open":
            prefix = "[OK]"
            msg = "Port open"
        elif status == "closed":
            prefix = "[FAIL]"
            msg = "Port closed"
        elif status == "filtered":
            prefix = "[FAIL]"
            msg = "Port filtered or unreachable"
        elif status == "skipped":
            prefix = "[SKIP]"
            msg = "Skipped (host not reachable)"
        else:
            prefix = "[WARN]"
            msg = "Port check error"

        print(f"{prefix} {name} (port {port['port']})")
        line = f"    {msg}"
        if port["response_ms"] is not None:
            line += f" ({port['response_ms']:.1f}ms)"
        print(line)
        if port["banner"]:
            print(f"    Banner: {port['banner']}")
        print()

    print("=" * 60)
    print(f"Overall Status: {report['overall_status'].upper()}")
    if report["recommendations"]:
        print()
        print("Recommendations:")
        for rec in report["recommendations"]:
            print(f"  - {rec}")


def _identify_services(result: HostInfo) -> None:
    """Populate identified_services for a host based on open ports and banners."""
    identified = result.setdefault("identified_services", [])
    services = result.get("services", {})

    for port in result.get("open_ports", []):
        banner = services.get(port, "")

        if port == 5900:
            if banner.startswith("RFB "):
                label = "VNC/Screen Sharing"
            elif "HTTP" in banner:
                label = "VNC port open (HTTP detected)"
            else:
                label = "VNC/Screen Sharing"
            if label not in identified:
                identified.append(label)
        elif port == 3283:
            if "Apple Remote Desktop" not in identified:
                identified.append("Apple Remote Desktop")

        # LLM services
        if port == 1234 and (("LM Studio" in banner) or ("HTTP" in banner)):
            if "LMStudio" not in identified:
                identified.append("LMStudio")
        elif port == 11434 and "Ollama" in banner:
            if "Ollama" not in identified:
                identified.append("Ollama")
        elif banner and "gradio" in banner.lower():
            if "Gradio" not in identified:
                identified.append("Gradio")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Network scanner for LLM-capable machines and screen sharing"
    )
    parser.add_argument(
        "-n",
        "--network",
        help="Network to scan (e.g., 192.168.1.0/24)",
        default=None,
    )
    parser.add_argument(
        "-p",
        "--ports",
        help="Additional ports to scan (comma-separated)",
        default="",
    )
    parser.add_argument(
        "-t",
        "--threads",
        help="Number of threads to use",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover screen sharing services via mDNS/Bonjour",
    )
    parser.add_argument(
        "--diagnose",
        metavar="HOST",
        help="Diagnose connectivity for a specific host",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="mDNS discovery timeout in seconds (for --discover)",
    )

    args = parser.parse_args()

    if args.diagnose:
        report = diagnose_host(args.diagnose)
        _print_diagnostic(report)
        return

    mdns_result: Optional[DiscoveryResult] = None
    mdns_by_ip: Dict[str, List[DiscoveredService]] = {}

    if args.discover:
        print(
            f"Discovering screen sharing services via mDNS (timeout: "
            f"{args.timeout:.0f}s)..."
        )
        print("-" * 60)
        mdns_result = discover_screen_sharing_services(timeout=args.timeout)

        print()
        print("=== mDNS Discovery Results ===")
        print()

        if mdns_result["error"]:
            print(f"Warning: mDNS discovery unavailable ({mdns_result['error']})")
        elif not mdns_result["services"]:
            print("No devices found advertising screen sharing services.")
            print()
            print(
                "Possible reasons:\n"
                "  - No devices with Screen Sharing enabled on this network\n"
                "  - mDNS traffic blocked by network configuration\n"
                "  - Devices are on a different subnet/VLAN"
            )
        else:
            for svc in mdns_result["services"]:
                print(f"  {svc['name']}")
                print(f"    IP: {svc['ip']}")
                print(f"    Port: {svc['port']}")
                print(f"    Service: {svc['service_type']}")
                print(f"    Hostname: {svc['hostname']}")
                print()
                mdns_by_ip.setdefault(svc["ip"], []).append(svc)

        print()
        print(
            f"Discovery complete in {mdns_result['duration_seconds']:.2f}s. "
            f"Found {len(mdns_result['services'])} devices."
        )
        print()

        # If only discovery was requested (no network/ports specified),
        # skip the full port scan.
        if args.network is None and not args.ports:
            return

        print("=== Port Scan Results ===")
        print()

    # Common ports for LLM services
    # 1234 - LMStudio default
    # 8080, 8000, 5000 - Common web/API ports
    # 11434 - Ollama default
    # 7860 - Gradio default
    # 5900 - VNC / Screen Sharing
    # 3283 - Apple Remote Desktop (TCP)
    default_ports = [1234, 8080, 8000, 5000, 11434, 7860, 3000, 5900, 3283]

    # Add custom ports if specified
    if args.ports:
        custom_ports = [
            int(p.strip()) for p in args.ports.split(",") if p.strip().isdigit()
        ]
        default_ports.extend(custom_ports)

    ports = sorted(set(default_ports))  # Remove duplicates and sort

    # Get network to scan
    network = args.network or get_local_network()

    print(f"Scanning network: {network}")
    print(f"Ports: {', '.join(map(str, ports))}")
    print(f"Using {args.threads} threads")
    print("-" * 60)

    try:
        # Create network object
        net = ipaddress.ip_network(network, strict=False)

        # Scan all hosts in the network
        active_hosts: List[HostInfo] = []

        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            # Submit all scanning tasks
            future_to_ip = {executor.submit(scan_host, ip, ports): ip for ip in net.hosts()}

            # Process results as they complete
            for future in as_completed(future_to_ip):
                result = future.result()

                if result["alive"] or result["open_ports"]:
                    _identify_services(result)
                    active_hosts.append(result)

                    # Print result immediately
                    print(f"\nHost: {result['ip']}")
                    if result["alive"]:
                        print("  Status: Online")

                    if result["open_ports"]:
                        open_ports_str = ", ".join(map(str, result["open_ports"]))
                        print(f"  Open ports: {open_ports_str}")

                        for port, banner in result["services"].items():
                            print(f"  Port {port} banner: {banner}")

                    if "identified_services" in result and result["identified_services"]:
                        for service in result["identified_services"]:
                            if service == "VNC/Screen Sharing":
                                print("  [VNC] VNC/Screen Sharing on port 5900")
                            elif service == "VNC port open (HTTP detected)":
                                print("  [VNC] VNC port open (HTTP detected)")
                            elif service == "Apple Remote Desktop":
                                print("  [ARD] Apple Remote Desktop on port 3283")
                            elif service == "LMStudio":
                                print("  [LLM] Likely LMStudio instance on port 1234")
                            elif service == "Ollama":
                                print("  [LLM] Ollama instance on port 11434")
                            elif service == "Gradio":
                                print("  [LLM] Gradio interface on port 7860")

                    # Annotate with mDNS information if available.
                    if mdns_by_ip.get(result["ip"]):
                        for svc in mdns_by_ip[result["ip"]]:
                            print(
                                f"  [mDNS] {svc['name']} "
                                f"({svc['service_type']} via Bonjour)"
                            )

        print("\n" + "=" * 60)
        print(f"Scan complete. Found {len(active_hosts)} active hosts")

        # Summary of LLM-capable hosts
        llm_hosts = []
        for host in active_hosts:
            if any(p in [1234, 11434] for p in host["open_ports"]):
                llm_hosts.append(host["ip"])

        if llm_hosts:
            print("\nPotential LLM hosts:")
            for ip in llm_hosts:
                print(f"  - {ip}")

        # Summary of screen sharing hosts
        screen_sharing_hosts = [
            host
            for host in active_hosts
            if "identified_services" in host
            and any(
                s in ("VNC/Screen Sharing", "Apple Remote Desktop")
                for s in host["identified_services"]
            )
        ]
        if screen_sharing_hosts:
            print("\nScreen Sharing hosts:")
            for host in screen_sharing_hosts:
                labels = ", ".join(host.get("identified_services", []))
                print(f"  - {host['ip']} ({labels})")

    except Exception as e:
        print(f"Error during scan: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
