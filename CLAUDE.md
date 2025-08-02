# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LANCompute is a Python utility for discovering machines on a local network that are capable of running Large Language Model (LLM) processes. It scans for common LLM services like LMStudio, Ollama, and Gradio.

## Core Architecture

### Main Components

1. **network_scanner.py** - The primary application that:
   - Auto-detects the local subnet using platform-specific commands
   - Performs multi-threaded network scanning
   - Checks host availability via ping
   - Scans specific ports used by LLM services
   - Attempts banner grabbing for service identification

### Key Service Ports

The scanner targets these default ports:
- 1234 (LMStudio)
- 11434 (Ollama)
- 7860 (Gradio)
- 8080, 8000, 5000, 3000 (Common web/API ports)

## Development Commands

### Running the Scanner

```bash
# Basic scan of auto-detected network
python network_scanner.py

# Scan specific network
python network_scanner.py -n 192.168.1.0/24

# Scan with additional ports
python network_scanner.py -p 9090 9091 9092

# Adjust thread count (default: 50)
python network_scanner.py -t 100
```

### Type Checking

```bash
# Run mypy for type checking (when type hints are added)
mypy network_scanner.py
```

## Code Patterns and Conventions

1. **Error Handling**: All network operations are wrapped in try/except blocks to handle connection failures gracefully
2. **Threading**: Uses concurrent.futures.ThreadPoolExecutor for parallel scanning
3. **Cross-platform Support**: Handles Windows, macOS, and Linux for subnet detection
4. **No External Dependencies**: Uses only Python standard library modules

## Important Implementation Details

1. **Subnet Detection**: The `get_subnet()` function uses platform-specific commands:
   - Windows: `ipconfig`
   - macOS/Linux: `ifconfig` or `ip addr show`
   - Falls back to 192.168.1.0/24 if detection fails

2. **Service Identification**: The `get_banner()` function sends a GET request to identify HTTP-based services

3. **Host Discovery**: Uses platform-specific ping commands with appropriate flags

## Future Enhancements to Consider

1. Add type hints throughout the codebase
2. Implement configuration file support for saved networks and custom ports
3. Add logging instead of print statements
4. Create unit tests for network utilities
5. Add JSON output format option
6. Implement service-specific detection logic (e.g., Ollama API endpoints)

## Claude Agents

The project includes 46 specialized AI agent personas in `.claude/agents/` for various development tasks. These can be leveraged for:
- Code reviews and quality assurance
- Architecture decisions
- Testing strategies
- Documentation improvements
- Language-specific expertise