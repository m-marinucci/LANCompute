#!/usr/bin/env python3
"""
Network scanner to discover machines suitable for running LLM processes.
Scans for common ports used by LMStudio and similar services.
"""

import socket
import subprocess
import sys
import threading
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import platform

def get_local_network():
    """Get the local network subnet."""
    try:
        # Get local IP address
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # For macOS/Linux, get more accurate network info
        if platform.system() != "Windows":
            cmd = "ifconfig" if platform.system() == "Darwin" else "ip addr"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
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
                            except:
                                continue
        
        # Convert to network subnet
        ip_parts = local_ip.split('.')
        network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
        return network
    except Exception as e:
        print(f"Error detecting network: {e}")
        return "192.168.1.0/24"  # Default fallback

def ping_host(ip):
    """Check if a host is reachable via ping."""
    try:
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', '-W', '1', str(ip)]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except:
        return False

def scan_port(ip, port, timeout=1):
    """Check if a specific port is open on a host."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((str(ip), port))
        sock.close()
        return result == 0
    except:
        return False

def get_service_banner(ip, port, timeout=2):
    """Try to get service banner from open port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((str(ip), port))
        
        # Send HTTP request for common web services
        if port in [1234, 8080, 5000, 8000, 3000]:
            sock.send(b"GET / HTTP/1.0\r\n\r\n")
            banner = sock.recv(1024).decode('utf-8', errors='ignore')
        else:
            banner = sock.recv(1024).decode('utf-8', errors='ignore')
        
        sock.close()
        return banner.strip()
    except:
        return ""

def scan_host(ip, ports):
    """Scan a single host for open ports and services."""
    host_info = {
        'ip': str(ip),
        'alive': False,
        'open_ports': [],
        'services': {}
    }
    
    # First check if host is alive
    if ping_host(ip):
        host_info['alive'] = True
        
        # Scan specified ports
        for port in ports:
            if scan_port(ip, port):
                host_info['open_ports'].append(port)
                
                # Try to get service banner
                banner = get_service_banner(ip, port)
                if banner:
                    host_info['services'][port] = banner[:100]  # Limit banner length
    
    return host_info

def main():
    parser = argparse.ArgumentParser(description='Network scanner for LLM-capable machines')
    parser.add_argument('-n', '--network', help='Network to scan (e.g., 192.168.1.0/24)', 
                        default=None)
    parser.add_argument('-p', '--ports', help='Additional ports to scan (comma-separated)', 
                        default='')
    parser.add_argument('-t', '--threads', help='Number of threads to use', 
                        type=int, default=50)
    
    args = parser.parse_args()
    
    # Common ports for LLM services
    # 1234 - LMStudio default
    # 8080, 8000, 5000 - Common web/API ports
    # 11434 - Ollama default
    # 7860 - Gradio default
    default_ports = [1234, 8080, 8000, 5000, 11434, 7860, 3000]
    
    # Add custom ports if specified
    if args.ports:
        custom_ports = [int(p.strip()) for p in args.ports.split(',') if p.strip().isdigit()]
        default_ports.extend(custom_ports)
    
    ports = list(set(default_ports))  # Remove duplicates
    
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
        active_hosts = []
        
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            # Submit all scanning tasks
            future_to_ip = {executor.submit(scan_host, ip, ports): ip 
                          for ip in net.hosts()}
            
            # Process results as they complete
            for future in as_completed(future_to_ip):
                result = future.result()
                
                if result['alive'] or result['open_ports']:
                    active_hosts.append(result)
                    
                    # Print result immediately
                    print(f"\nHost: {result['ip']}")
                    if result['alive']:
                        print("  Status: Online")
                    
                    if result['open_ports']:
                        print(f"  Open ports: {', '.join(map(str, result['open_ports']))}")
                        
                        for port, banner in result['services'].items():
                            print(f"  Port {port} banner: {banner}")
                            
                            # Check for known LLM services
                            if port == 1234 and ('LM Studio' in banner or 'HTTP' in banner):
                                print(f"  🚀 Likely LMStudio instance on port {port}")
                            elif port == 11434 and 'Ollama' in banner:
                                print(f"  🦙 Ollama instance detected on port {port}")
                            elif 'gradio' in banner.lower():
                                print(f"  🎯 Gradio interface detected on port {port}")
        
        print("\n" + "=" * 60)
        print(f"Scan complete. Found {len(active_hosts)} active hosts")
        
        # Summary of LLM-capable hosts
        llm_hosts = []
        for host in active_hosts:
            if any(p in [1234, 11434] for p in host['open_ports']):
                llm_hosts.append(host['ip'])
        
        if llm_hosts:
            print(f"\nPotential LLM hosts:")
            for ip in llm_hosts:
                print(f"  - {ip}")
        
    except Exception as e:
        print(f"Error during scan: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()