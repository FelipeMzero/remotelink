"""
RemoteLink - Machine Identity & Network Discovery
Generates unique machine codes and handles network discovery
"""

import socket
import uuid
import hashlib
import platform
import subprocess
import json
import os
import ipaddress
import struct
from pathlib import Path


# Where the machine code is stored locally
IDENTITY_FILE = Path.home() / ".remotelink" / "identity.json"


def _get_mac_address() -> str:
    """Get MAC address of the primary network interface."""
    mac = uuid.getnode()
    return ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(0, 48, 8))


def _get_machine_fingerprint() -> str:
    """Generate a stable fingerprint based on hardware info."""
    parts = []

    # MAC address (stable)
    parts.append(_get_mac_address())

    # Hostname
    parts.append(socket.gethostname())

    # Platform
    parts.append(platform.system())
    parts.append(platform.machine())

    fingerprint = "|".join(parts)
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def generate_access_code(fingerprint: str) -> str:
    """
    Generates a human-friendly 9-character access code from the fingerprint.
    Format: XXX-XXX-XXX (uppercase alphanumeric, no ambiguous chars)
    """
    # Remove ambiguous chars: 0, O, I, 1, L
    charset = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    
    # Use first 18 hex chars of hash for 9 code chars
    h = hashlib.md5(fingerprint.encode()).hexdigest()
    
    code_chars = []
    for i in range(9):
        val = int(h[i * 2: i * 2 + 2], 16)
        code_chars.append(charset[val % len(charset)])
    
    code = "".join(code_chars)
    return f"{code[0:3]}-{code[3:6]}-{code[6:9]}"


def get_local_ip() -> str:
    """Get the primary local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_local_subnet() -> str:
    """Get the local subnet (e.g., '192.168.1')."""
    ip = get_local_ip()
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3])
    return "192.168.1"


def load_or_create_identity() -> dict:
    """Load existing identity or create a new one."""
    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if IDENTITY_FILE.exists():
        try:
            with open(IDENTITY_FILE, "r") as f:
                data = json.load(f)
                # Validate it still matches hardware
                current_fp = _get_machine_fingerprint()
                if data.get("fingerprint") == current_fp:
                    return data
        except Exception:
            pass

    # Create new identity
    fingerprint = _get_machine_fingerprint()
    access_code = generate_access_code(fingerprint)
    
    identity = {
        "fingerprint": fingerprint,
        "access_code": access_code,
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "machine": platform.machine(),
    }

    with open(IDENTITY_FILE, "w") as f:
        json.dump(identity, f, indent=2)

    return identity


def get_machine_info() -> dict:
    """Get full machine information for display."""
    identity = load_or_create_identity()
    local_ip = get_local_ip()
    
    return {
        "access_code": identity["access_code"],
        "hostname": socket.gethostname(),
        "local_ip": local_ip,
        "platform": platform.system(),
        "platform_version": platform.version()[:40],
        "machine_arch": platform.machine(),
        "fingerprint": identity["fingerprint"][:12] + "...",
    }


def resolve_target(target: str) -> dict | None:
    """
    Try to resolve a target (hostname, IP, or access code) to connection info.
    Returns dict with 'ip', 'hostname', 'method', or None if unresolvable.
    """
    target = target.strip()
    
    # Check if it looks like an access code (XXX-XXX-XXX)
    if len(target) == 11 and target[3] == '-' and target[7] == '-':
        return {
            "display": target,
            "method": "access_code",
            "code": target,
            "ip": None,
            "hostname": None,
            "status": "pending"
        }
    
    # Check if it's an IP address
    try:
        ipaddress.ip_address(target)
        # Valid IP - try reverse DNS
        try:
            hostname = socket.gethostbyaddr(target)[0]
        except Exception:
            hostname = target
        return {
            "display": target,
            "method": "ip",
            "ip": target,
            "hostname": hostname,
            "status": "pending"
        }
    except ValueError:
        pass
    
    # Treat as hostname - try to resolve
    try:
        ip = socket.gethostbyname(target)
        return {
            "display": target,
            "method": "hostname",
            "ip": ip,
            "hostname": target,
            "status": "pending"
        }
    except socket.gaierror:
        return {
            "display": target,
            "method": "hostname",
            "ip": None,
            "hostname": target,
            "status": "unresolved"
        }


def ping_host(ip: str, timeout: float = 1.0) -> bool:
    """Quick ping check if host is reachable."""
    try:
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]
        
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout + 1
        )
        return result.returncode == 0
    except Exception:
        return False


def scan_local_network(progress_callback=None) -> list[dict]:
    """
    Scan local subnet for machines running RemoteLink.
    Returns list of discovered machines.
    """
    subnet = get_local_subnet()
    found = []
    
    import threading
    lock = threading.Lock()
    
    def check_host(i):
        ip = f"{subnet}.{i}"
        if ip == get_local_ip():
            return
        
        # Quick TCP check on RemoteLink port
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex((ip, 52340))
            s.close()
            
            if result == 0:
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except Exception:
                    hostname = ip
                
                with lock:
                    found.append({
                        "ip": ip,
                        "hostname": hostname,
                        "method": "scan",
                        "status": "online"
                    })
        except Exception:
            pass
        
        if progress_callback:
            progress_callback(i / 254.0)
    
    threads = []
    for i in range(1, 255):
        t = threading.Thread(target=check_host, args=(i,), daemon=True)
        threads.append(t)
        t.start()
        
        # Limit concurrent threads
        if len(threads) >= 50:
            for t in threads:
                t.join(timeout=1)
            threads = []
    
    for t in threads:
        t.join(timeout=2)
    
    return found
