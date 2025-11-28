# Feature: Screen Sharing Discovery and Diagnostics

## Feature Description
Enhance LANCompute's network scanner to detect screen sharing services (VNC, Apple Remote Desktop) and provide diagnostic capabilities for troubleshooting connection failures. This includes mDNS/Bonjour discovery for Apple devices advertising screen sharing services, extended port scanning for remote desktop protocols, and a dedicated diagnostic mode for verifying connectivity to specific hosts.

## User Story
As a network administrator or developer
I want to discover and diagnose screen sharing services on my LAN
So that I can verify connectivity before attempting screen sharing connections and troubleshoot failures like "Connection failed to 'Massimiliano's MacBook Pro'"

## Problem Statement
Users experience screen sharing connection failures without visibility into whether the target machine is reachable, whether the screen sharing service is running, or whether firewall rules are blocking access. Currently, LANCompute focuses on LLM service discovery but lacks support for remote desktop/screen sharing services that are essential for distributed computing management.

## Solution Statement
Extend the network scanner with three capabilities:
1. **Screen sharing port detection** - Add VNC (5900) and Apple Remote Desktop (3283) to default port scans
2. **mDNS/Bonjour discovery** - Use the `zeroconf` library to discover Apple devices advertising `_rfb._tcp` and `_screensharing._tcp` services
3. **Diagnostic mode** - A targeted diagnostic function that checks ping, port 5900, SSH (22), and provides actionable troubleshooting output for a specific host

## Non-Functional Requirements

### Performance
- **Full /24 subnet scan**: Complete within 30 seconds using default 50 threads
- **Single host diagnostic**: Complete within 5 seconds
- **mDNS discovery**: Default timeout of 5 seconds; configurable up to 30 seconds via `--timeout`

### Resource Usage
- **Memory**: mDNS discovery should not exceed 50MB additional memory
- **CPU**: Scanning should yield to other processes; avoid 100% CPU utilization
- **Network**: No more than 50 concurrent connections (existing thread pool limit)

### Latency
- **Port scan per host**: <500ms per port with 1-second socket timeout
- **Ping check**: 1-second timeout per host (matches existing behavior)

## Data Structures

### DiscoveredService (mDNS discovery result)
```python
from typing import TypedDict, Optional, List

class DiscoveredService(TypedDict):
    """Single service discovered via mDNS/Bonjour."""
    name: str              # e.g., "Massimiliano's MacBook Pro"
    ip: str                # e.g., "192.168.1.42"
    port: int              # e.g., 5900
    service_type: str      # "_rfb._tcp.local." or "_screensharing._tcp.local."
    hostname: str          # e.g., "Massimilianos-MacBook-Pro.local."

class DiscoveryResult(TypedDict):
    """Result from discover_screen_sharing_services()."""
    services: List[DiscoveredService]
    duration_seconds: float
    error: Optional[str]   # None on success, error message on failure
```

### DiagnosticReport (diagnose_host result)
```python
class PortCheck(TypedDict):
    """Result of checking a single port."""
    port: int
    name: str              # e.g., "VNC", "ARD", "SSH"
    status: str            # "open", "closed", "filtered", "error"
    banner: Optional[str]  # Service banner if retrieved
    response_ms: Optional[float]

class DiagnosticReport(TypedDict):
    """Result from diagnose_host()."""
    target: str            # Original target (hostname or IP)
    resolved_ip: Optional[str]  # Resolved IP, None if resolution failed
    resolution_error: Optional[str]
    ping: PingResult
    ports: List[PortCheck]
    recommendations: List[str]
    overall_status: str    # "reachable", "partial", "unreachable", "error"

class PingResult(TypedDict):
    """Result of ping check."""
    success: bool
    response_ms: Optional[float]
    error: Optional[str]   # "timeout", "host_unreachable", "permission_denied", None
```

### Extended HostInfo (existing scan_host result, extended)
```python
# Existing structure, screen sharing info integrated inline
class HostInfo(TypedDict):
    ip: str
    alive: bool
    open_ports: List[int]
    services: Dict[int, str]  # port -> banner
    # New field for identified service types
    identified_services: List[str]  # e.g., ["VNC/Screen Sharing", "LMStudio"]
```

## Service Detection Rules

### VNC/Screen Sharing (Port 5900)
Detection is **port-based with banner enhancement**:
1. Port 5900 open = identified as "VNC/Screen Sharing"
2. Banner inspection for confirmation:
   - Banner starts with `RFB ` (e.g., "RFB 003.008") = confirmed VNC protocol
   - Any HTTP response = likely web service on non-standard port, still report as "VNC port open (HTTP detected)"

### Apple Remote Desktop (Port 3283)
Detection is **port-based only** (TCP):
1. Port 3283 TCP open = identified as "Apple Remote Desktop"
2. No banner grabbing attempted (ARD does not send banners on connect)

**Note**: UDP 3283 probing is **deferred** to a future enhancement (see Notes section).

### SSH (Port 22)
Detection for diagnostic mode fallback:
1. Port 22 open = identified as "SSH"
2. Banner inspection: Look for `SSH-` prefix (e.g., "SSH-2.0-OpenSSH_8.9")

## CLI Output Examples

### Default Scan with Screen Sharing Ports
```
$ python -m lancompute.network_scanner

Scanning network: 192.168.1.0/24
Ports: 1234, 3283, 5000, 5900, 7860, 8000, 8080, 11434
Using 50 threads
------------------------------------------------------------

Host: 192.168.1.42
  Status: Online
  Open ports: 5900, 22
  Port 5900 banner: RFB 003.008
  [VNC] VNC/Screen Sharing on port 5900

Host: 192.168.1.100
  Status: Online
  Open ports: 1234, 8080
  Port 1234 banner: HTTP/1.1 200 OK
  [LLM] Likely LMStudio instance on port 1234

============================================================
Scan complete. Found 2 active hosts

Screen Sharing hosts:
  - 192.168.1.42 (VNC on 5900)

Potential LLM hosts:
  - 192.168.1.100
```

### mDNS Discovery Mode (--discover)
```
$ python -m lancompute.network_scanner --discover

Discovering screen sharing services via mDNS (timeout: 5s)...
------------------------------------------------------------

Found 2 devices advertising screen sharing:

  Massimiliano's MacBook Pro
    IP: 192.168.1.42
    Port: 5900
    Service: _rfb._tcp.local.
    Hostname: Massimilianos-MacBook-Pro.local.

  Studio iMac
    IP: 192.168.1.55
    Port: 5900
    Service: _screensharing._tcp.local.
    Hostname: Studio-iMac.local.

============================================================
Discovery complete in 5.02s. Found 2 devices.
```

### mDNS Discovery - No Devices Found
```
$ python -m lancompute.network_scanner --discover

Discovering screen sharing services via mDNS (timeout: 5s)...
------------------------------------------------------------

No devices found advertising screen sharing services.

Possible reasons:
  - No macOS/Apple devices with Screen Sharing enabled on this network
  - mDNS traffic blocked by network configuration
  - Devices are on a different subnet/VLAN

Tip: Use --diagnose <hostname-or-ip> to check a specific host directly.
```

### mDNS Discovery - Library Failure (Graceful Degradation)
```
$ python -m lancompute.network_scanner --discover

Discovering screen sharing services via mDNS (timeout: 5s)...
------------------------------------------------------------

Warning: mDNS discovery unavailable (zeroconf initialization failed: [Errno 49] Can't assign requested address)

Falling back to port scan for screen sharing services...
[Proceeds with normal port scan for 5900, 3283]
```

### Diagnostic Mode - Success
```
$ python -m lancompute.network_scanner --diagnose "Massimiliano's MacBook Pro.local"

Diagnosing: Massimiliano's MacBook Pro.local
------------------------------------------------------------

[OK] DNS Resolution
    Resolved to: 192.168.1.42

[OK] Ping Check
    Host is reachable (12.3ms)

[OK] VNC/Screen Sharing (port 5900)
    Port open (8.2ms)
    Banner: RFB 003.008

[--] Apple Remote Desktop (port 3283)
    Port closed

[OK] SSH (port 22)
    Port open (5.1ms)
    Banner: SSH-2.0-OpenSSH_9.0

============================================================
Overall Status: REACHABLE

Screen sharing should work. If connection still fails:
  - Check that you have permission to connect (System Settings > Sharing)
  - Verify your user account is in the allowed users list
```

### Diagnostic Mode - Host Unreachable
```
$ python -m lancompute.network_scanner --diagnose 192.168.1.99

Diagnosing: 192.168.1.99
------------------------------------------------------------

[OK] DNS Resolution
    Using IP directly: 192.168.1.99

[FAIL] Ping Check
    Host unreachable (no response after 1000ms)

[SKIP] VNC/Screen Sharing (port 5900)
    Skipped (host not reachable)

[SKIP] Apple Remote Desktop (port 3283)
    Skipped (host not reachable)

[SKIP] SSH (port 22)
    Skipped (host not reachable)

============================================================
Overall Status: UNREACHABLE

Recommendations:
  - Verify the host is powered on and connected to the network
  - Check that you're on the same network/VLAN as the target
  - Confirm the IP address is correct (try: ping 192.168.1.99)
  - Check if a firewall is blocking ICMP ping requests
```

### Diagnostic Mode - Partial Connectivity
```
$ python -m lancompute.network_scanner --diagnose 192.168.1.42

Diagnosing: 192.168.1.42
------------------------------------------------------------

[OK] DNS Resolution
    Using IP directly: 192.168.1.42

[OK] Ping Check
    Host is reachable (15.7ms)

[FAIL] VNC/Screen Sharing (port 5900)
    Port closed or filtered

[--] Apple Remote Desktop (port 3283)
    Port closed

[OK] SSH (port 22)
    Port open (6.3ms)
    Banner: SSH-2.0-OpenSSH_9.0

============================================================
Overall Status: PARTIAL

Recommendations:
  - Screen Sharing is not enabled on the target Mac
  - Enable it: System Settings > General > Sharing > Screen Sharing
  - Alternative: SSH is available - use SSH tunnel for VNC:
      ssh -L 5900:localhost:5900 user@192.168.1.42
      Then connect to: vnc://localhost:5900
```

### Diagnostic Mode - Ping Permission Denied
```
$ python -m lancompute.network_scanner --diagnose 192.168.1.42

Diagnosing: 192.168.1.42
------------------------------------------------------------

[OK] DNS Resolution
    Using IP directly: 192.168.1.42

[WARN] Ping Check
    Permission denied (ICMP requires elevated privileges)
    Proceeding with port checks...

[OK] VNC/Screen Sharing (port 5900)
    Port open (8.2ms)
    Banner: RFB 003.008
...
```

### Combined Flags (--discover with normal scan)
```
$ python -m lancompute.network_scanner --discover -n 192.168.1.0/24

Discovering screen sharing services via mDNS (timeout: 5s)...

=== mDNS Discovery Results ===

  Massimiliano's MacBook Pro (192.168.1.42:5900)
    Service: _rfb._tcp.local.

=== Port Scan Results ===

Scanning network: 192.168.1.0/24
Ports: 1234, 3283, 5000, 5900, 7860, 8000, 8080, 11434
Using 50 threads
------------------------------------------------------------

Host: 192.168.1.42
  Status: Online
  Open ports: 5900, 22
  [VNC] VNC/Screen Sharing on port 5900
  [mDNS] Massimiliano's MacBook Pro (via Bonjour)

Host: 192.168.1.100
  Status: Online
  Open ports: 1234
  [LLM] Likely LMStudio instance on port 1234

============================================================
Scan complete. Found 2 active hosts
```

**Flag combination behavior**: When `--discover` is combined with a network scan, mDNS discovery runs first (in parallel with scan start), and results are merged into the host list. Hosts found via mDNS are annotated with their Bonjour name. mDNS-only devices not responding to port scan are listed in a separate "mDNS-only devices" section.

## Output Formatting - Emoji and Text Equivalents

All indicators include both emoji and text labels for compatibility:

| Service | Emoji Output | Text-Only Equivalent |
|---------|--------------|---------------------|
| VNC/Screen Sharing | `[VNC] VNC/Screen Sharing on port 5900` | Same (emoji optional prefix) |
| Apple Remote Desktop | `[ARD] Apple Remote Desktop on port 3283` | Same |
| SSH | `[SSH] SSH on port 22` | Same |
| LMStudio | `[LLM] Likely LMStudio instance on port 1234` | Same |
| Ollama | `[LLM] Ollama instance on port 11434` | Same |
| Gradio | `[LLM] Gradio interface on port 7860` | Same |

Emoji usage is **optional** and controlled by terminal capability detection or `--no-emoji` flag (future enhancement if needed).

## Security and Privacy

- **Local/LAN use only**: This tool is designed for scanning your own local network. Do not use on networks you don't own or have permission to scan.
- **No persistent storage**: Discovered hosts, IPs, and device names are not stored to disk by default. Results are printed to stdout only.
- **No remote transmission**: Scan results are never sent to external services.
- **Firewall compliance**: The scanner uses standard TCP connect() and ICMP ping. It does not attempt to bypass firewalls or use stealth techniques.

## Relevant Files
Use these files to implement the feature:

- `src/lancompute/network_scanner.py` - Main scanner module to extend with screen sharing ports, mDNS discovery integration, and diagnostic mode
- `tests/test_network_scanner.py` - Existing tests to extend with new functionality coverage
- `pyproject.toml` - Add `zeroconf` dependency for mDNS discovery
- `README.md` - Update documentation with new features and CLI options

### New Files
- `src/lancompute/mdns_discovery.py` - New module for mDNS/Bonjour service discovery (keeps network_scanner.py focused)
- `tests/test_mdns_discovery.py` - Tests for mDNS discovery functionality

## Implementation Plan

### Phase 1: Foundation
- Add `zeroconf` library dependency to `pyproject.toml`
- Add screen sharing ports (5900, 3283) to default port list in `network_scanner.py`
- Add service identification for VNC and ARD using detection rules defined above

### Phase 2: Core Implementation
- Create `mdns_discovery.py` module with:
  - `ScreenSharingListener` class implementing zeroconf `ServiceListener`
  - Service type constants for `_rfb._tcp.local.` and `_screensharing._tcp.local.`
  - **Synchronous** `discover_screen_sharing_services(timeout=5)` function that blocks until timeout
  - Graceful error handling: return `DiscoveryResult` with `error` field set on failure
  - Results use `DiscoveredService` TypedDict structure
- Add `diagnose_host(target: str) -> DiagnosticReport` function to `network_scanner.py`:
  - Accept hostname or IP
  - Resolve hostname via `socket.gethostbyname()` with error handling
  - Ping check using existing `ping_host()` with enhanced error classification
  - Port checks for 5900, 3283, 22 with timing
  - Generate recommendations based on results
  - Return `DiagnosticReport` TypedDict

### Phase 3: Integration
- Add `--discover` CLI flag for mDNS discovery mode
- Add `--diagnose <host>` CLI flag for diagnostic mode
- Add `--timeout` flag for mDNS discovery timeout (default 5s)
- Integrate mDNS results with standard scan output (merged host list with annotations)
- Add screen sharing detection indicators with text labels

## Step by Step Tasks

### Step 1: Add zeroconf dependency
- Edit `pyproject.toml` to add `zeroconf>=0.100.0` to dependencies
- Run `uv pip install -e .` to install

### Step 2: Extend default ports for screen sharing
- Edit `src/lancompute/network_scanner.py`
- Add ports 5900 (VNC) and 3283 (ARD) to `default_ports` list
- Do NOT add 5900/3283 to `HTTP_PORTS` (VNC uses RFB protocol, ARD has no banner)
- Add service identification logic using detection rules:
  - Port 5900 open: print `[VNC] VNC/Screen Sharing on port 5900`
  - Port 5900 with `RFB ` banner prefix: confirmed VNC
  - Port 3283 open: print `[ARD] Apple Remote Desktop on port 3283`

### Step 3: Create mDNS discovery module
- Create `src/lancompute/mdns_discovery.py`
- Define `DiscoveredService` and `DiscoveryResult` TypedDicts
- Implement `ScreenSharingListener(ServiceListener)` class:
  - `add_service()`: extract name, IP, port, store in results list
  - `remove_service()`: no-op (we only care about current state)
  - `update_service()`: no-op
- Implement `discover_screen_sharing_services(timeout: float = 5.0) -> DiscoveryResult`:
  - **Synchronous function** (blocks for `timeout` seconds)
  - Wrap zeroconf initialization in try/except
  - On zeroconf failure: return `DiscoveryResult(services=[], error="message")`
  - Browse both `_rfb._tcp.local.` and `_screensharing._tcp.local.`
  - Use `time.sleep(timeout)` then close browser
  - Return collected services

### Step 4: Write tests for mDNS discovery
- Create `tests/test_mdns_discovery.py`
- **Unit tests** (no network, all mocks):
  - Test `ScreenSharingListener.add_service()` populates results correctly
  - Test `discover_screen_sharing_services()` returns empty list on timeout with no services
  - Test `discover_screen_sharing_services()` returns error field when zeroconf fails
  - Test result structure matches `DiscoveryResult` TypedDict
- **Integration tests** (marked with `@pytest.mark.integration`):
  - Test actual mDNS discovery on local network (may find 0 devices, should not crash)

### Step 5: Implement diagnostic mode
- Add `diagnose_host(target: str) -> DiagnosticReport` function to `network_scanner.py`
- Define `PingResult`, `PortCheck`, `DiagnosticReport` TypedDicts
- Implement hostname resolution:
  - If target looks like IP (contains only digits and dots), use directly
  - Otherwise, use `socket.gethostbyname(target)` with try/except
  - On failure: set `resolution_error`, skip remaining checks
- Implement enhanced ping check:
  - Use existing `ping_host()` implementation (subprocess call)
  - Classify errors:
    - Return code 0: success
    - Return code 1: host unreachable
    - Return code 2: permission denied (some systems)
    - Exception: report as error
  - **Permission denied handling**: Log warning, continue with port checks (ports may still be reachable)
- Implement port checks for 5900, 3283, 22:
  - Use existing `scan_port()` function
  - Record response time using `time.time()` before/after
  - Capture banner for SSH (port 22) and VNC (port 5900)
- Generate recommendations based on results (see examples in CLI Output section)
- Determine `overall_status`:
  - "reachable": ping OK and at least VNC or ARD open
  - "partial": ping OK but VNC/ARD closed (SSH may be open)
  - "unreachable": ping failed
  - "error": resolution failed or other error

### Step 6: Write tests for diagnostic mode
- Add tests to `tests/test_network_scanner.py`
- **Unit tests** (mocked subprocess and socket):
  - `test_diagnose_host_success`: mock ping success, VNC open, returns "reachable"
  - `test_diagnose_host_unreachable`: mock ping failure, returns "unreachable"
  - `test_diagnose_host_partial`: mock ping success, VNC closed, SSH open, returns "partial"
  - `test_diagnose_host_resolution_failure`: invalid hostname, returns error
  - `test_diagnose_host_ping_permission_denied`: mock permission error, continues to port checks
  - `test_diagnose_host_recommendations`: verify correct recommendations generated

### Step 7: Integrate CLI options
- Add `--discover` flag: triggers mDNS discovery, prints results, exits (unless combined with scan)
- Add `--diagnose <host>` flag: runs diagnostic mode for single host, prints report, exits
- Add `--timeout <seconds>` flag: sets mDNS discovery timeout (default 5, max 30)
- Update argument parser with mutually exclusive group for `--diagnose` (can't combine with network scan)
- Allow `--discover` to combine with network scan (runs both, merges output)
- Handle graceful degradation: if zeroconf fails with `--discover`, warn and continue with port scan

### Step 8: Update output formatting
- Add service indicators with text labels:
  - `[VNC] VNC/Screen Sharing on port 5900`
  - `[ARD] Apple Remote Desktop on port 3283`
  - `[SSH] SSH on port 22`
- Format mDNS discovery results showing device name, IP, port, service type
- Format diagnostic output with `[OK]`, `[FAIL]`, `[WARN]`, `[SKIP]`, `[--]` prefixes
- Add summary sections for "Screen Sharing hosts" alongside existing "Potential LLM hosts"

### Step 9: Update documentation
- Update `README.md` with:
  - New CLI options (`--discover`, `--diagnose`, `--timeout`)
  - Examples for screen sharing discovery
  - Troubleshooting section for screen sharing connection failures
  - Security/privacy note about local-only scanning

### Step 10: Run validation commands
- Execute all validation commands listed below

## Testing Strategy

### Unit Tests (No Network, All Mocks)
- `test_mdns_discovery.py`:
  - Test `ScreenSharingListener.add_service()` callback stores service info
  - Test `ScreenSharingListener.remove_service()` is no-op
  - Test `discover_screen_sharing_services()` returns `DiscoveryResult` structure
  - Test discovery with mocked zeroconf failure returns error
  - Test empty discovery returns empty services list
- `test_network_scanner.py` (additions):
  - Test `diagnose_host()` with mock ping success/failure
  - Test `diagnose_host()` port checks with mock socket
  - Test hostname resolution success/failure
  - Test ping permission denied handling (continues with ports)
  - Test recommendation generation
  - Test screen sharing port detection in regular scan
  - Test VNC banner detection (`RFB ` prefix)

### Integration Tests (Require Network, Marked Separately)
Mark with `@pytest.mark.integration` so CI can skip if needed:
- Test actual mDNS discovery (may find 0 devices)
- Test ping to localhost
- Test port scan to localhost

### Edge Cases
- mDNS discovery on network with no Apple devices (empty result, no crash)
- mDNS discovery with zeroconf initialization failure (graceful degradation)
- Diagnostic mode with invalid hostname (resolution error)
- Diagnostic mode with IP vs hostname input
- Host reachable by ping but all ports closed
- Host with VNC open but ARD closed (and vice versa)
- Ping permission denied on restricted systems
- Network interface unavailable for mDNS
- Very long device names in mDNS results (truncation)
- IPv6 addresses (document as unsupported in v1)

## Acceptance Criteria
- [ ] VNC port 5900 and ARD port 3283 are scanned by default
- [ ] Screen sharing services are identified with `[VNC]` and `[ARD]` indicators
- [ ] `--discover` flag triggers mDNS discovery and lists Apple devices with screen sharing
- [ ] `--discover` gracefully degrades if zeroconf fails (warning + fallback to port scan)
- [ ] `--diagnose <host>` provides clear pass/fail status for ping, VNC, ARD, and SSH
- [ ] Diagnostic mode provides actionable recommendations based on results
- [ ] Ping permission denied is handled gracefully (warning, continue with ports)
- [ ] All existing tests continue to pass
- [ ] New functionality has >80% test coverage
- [ ] Unit tests have no network dependencies (all mocked)
- [ ] Integration tests are marked with `@pytest.mark.integration`
- [ ] Documentation updated with new features

## Validation Commands
Execute every command to validate the feature works correctly with zero regressions.

```bash
# Install dependencies
cd /Users/numinate/PY/LANCompute && uv pip install -e ".[test]"

# Run unit tests only (no network)
cd /Users/numinate/PY/LANCompute && uv run pytest -v -m "not integration"

# Run all tests including integration (requires network)
cd /Users/numinate/PY/LANCompute && uv run pytest --cov=src --cov-report=term-missing -v

# Run type checking
cd /Users/numinate/PY/LANCompute && uv run mypy src/

# Verify CLI help shows new options
cd /Users/numinate/PY/LANCompute && uv run python -m lancompute.network_scanner --help

# Test mDNS discovery (requires network)
cd /Users/numinate/PY/LANCompute && uv run python -m lancompute.network_scanner --discover

# Test diagnostic mode against localhost
cd /Users/numinate/PY/LANCompute && uv run python -m lancompute.network_scanner --diagnose localhost

# Test combined discover + scan
cd /Users/numinate/PY/LANCompute && uv run python -m lancompute.network_scanner --discover -n 192.168.1.0/24
```

## Notes

### Dependencies
- The `zeroconf` library (>=0.100.0) is pure Python and works on macOS, Linux, and Windows without requiring system Bonjour/Avahi installations

### Testing Environment
- mDNS discovery requires network access and may not work in all CI environments
- Mark integration tests with `@pytest.mark.integration` for easy CI filtering
- Unit tests must be fully isolated with mocked network calls

### Protocol Details
- Screen sharing port 5900 is the base VNC port; macOS may use 5900+display_number for multiple displays (5901, 5902, etc.) - scanning only 5900 for v1
- Apple Remote Desktop uses TCP 3283 for reporting/admin

### Deferred to Future Enhancement
- **ARD UDP 3283 probing**: UDP scanning is more complex and less reliable; TCP-only for v1
- **Multiple VNC display ports**: Scanning 5901-5909 for multi-display setups
- **IPv6 support**: Current implementation is IPv4 only
- **`--no-emoji` flag**: If emoji rendering issues are reported
- **SSH tunnel command generation**: Automatic generation of SSH tunnel commands when VNC is blocked but SSH is open

### Graceful Degradation
- If `zeroconf` library fails to initialize (network issues, permission errors), the scanner should:
  1. Print a warning message with the error
  2. Continue with port-based scanning for screen sharing services
  3. Never abort the entire scan due to mDNS failure

### Ping Implementation
- Uses existing `ping_host()` which calls system `ping` command via subprocess
- Cross-platform flags: `-c 1` (Unix) or `-n 1` (Windows), `-W 1` timeout
- Permission denied (ICMP blocked): treated as warning, not failure; port checks continue
- Host unreachable vs timeout: both reported as "unreachable" with appropriate error message
