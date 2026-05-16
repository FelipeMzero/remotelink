"""
RemoteLink - Machine Identity & Network Discovery
- Codigo de acesso somente numeros (formato XXX-XXX)
- Detecta todas as interfaces (cabeada + WiFi)
- Scan de rede sem travar a UI
"""

import socket
import uuid
import hashlib
import platform
import subprocess
import json
import os
import ipaddress
import re
import threading
from pathlib import Path

IDENTITY_FILE = Path.home() / ".remotelink" / "identity.json"
REMOTELINK_PORT = 52340


# ── Helpers de rede ────────────────────────────────────────────────────────────

def get_all_local_ips() -> list[str]:
    ips = set()
    try:
        for target in ("8.8.8.8", "1.1.1.1"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                s.connect((target, 80))
                ips.add(s.getsockname()[0])
                s.close()
            except Exception:
                pass

        try:
            hostname = socket.gethostname()
            _, _, addr_list = socket.gethostbyname_ex(hostname)
            ips.update(addr_list)
        except Exception:
            pass

        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                addr = info[4][0]
                if ":" not in addr:
                    ips.add(addr)
        except Exception:
            pass

        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["ipconfig"], capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    m = re.search(r'IPv4[^:]*:\s*(\d+\.\d+\.\d+\.\d+)', line)
                    if m:
                        ips.add(m.group(1))
            except Exception:
                pass

    except Exception:
        pass

    valid = []
    for ip in ips:
        try:
            obj = ipaddress.ip_address(ip)
            if not obj.is_loopback and not obj.is_link_local:
                valid.append(ip)
        except Exception:
            pass

    return sorted(valid) or ["127.0.0.1"]


def get_local_ip() -> str:
    ips = get_all_local_ips()
    for ip in ips:
        if ip.startswith(("192.168.", "10.", "172.")):
            return ip
    return ips[0] if ips else "127.0.0.1"


def get_all_subnets() -> list[str]:
    subnets = set()
    for ip in get_all_local_ips():
        parts = ip.split(".")
        if len(parts) == 4:
            subnets.add(".".join(parts[:3]))
    return list(subnets)


# ── Identidade da máquina ──────────────────────────────────────────────────────

def _get_mac_address() -> str:
    mac = uuid.getnode()
    return ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(0, 48, 8))


def _get_fingerprint() -> str:
    parts = [_get_mac_address(), socket.gethostname(),
             platform.system(), platform.machine()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def generate_access_code(fingerprint: str) -> str:
    """Gera codigo numerico no formato XXX-XXX (6 digitos)."""
    h = hashlib.md5(fingerprint.encode()).hexdigest()
    chars = []
    for i in range(6):
        val = int(h[i * 2: i * 2 + 2], 16)
        chars.append(str(val % 10))
    return f"{''.join(chars[0:3])}-{''.join(chars[3:6])}"


def normalize_code(code: str) -> str:
    """Remove tudo que nao for digito."""
    return re.sub(r'[^0-9]', '', code)


def _is_valid_code(code: str) -> bool:
    """Verifica se o codigo esta no formato numerico XXX-XXX."""
    if not code or len(code) != 7:
        return False
    parts = code.split("-")
    if len(parts) != 2:
        return False
    return len(parts[0]) == 3 and len(parts[1]) == 3 and parts[0].isdigit() and parts[1].isdigit()


def load_or_create_identity() -> dict:
    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if IDENTITY_FILE.exists():
        try:
            with open(IDENTITY_FILE) as f:
                data = json.load(f)
            fp = _get_fingerprint()
            if data.get("fingerprint") == fp:
                code = data.get("access_code", "")
                if _is_valid_code(code):
                    return data
                # Codigo antigo ou corrompido — regenera
                data["access_code"] = generate_access_code(fp)
                with open(IDENTITY_FILE, "w") as f:
                    json.dump(data, f, indent=2)
                return data
        except Exception:
            pass

    fp = _get_fingerprint()
    identity = {
        "fingerprint": fp,
        "access_code": generate_access_code(fp),
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "machine": platform.machine(),
    }
    with open(IDENTITY_FILE, "w") as f:
        json.dump(identity, f, indent=2)
    return identity


def get_machine_info() -> dict:
    identity = load_or_create_identity()
    all_ips = get_all_local_ips()
    local_ip = get_local_ip()
    return {
        "access_code": identity["access_code"],
        "hostname": socket.gethostname(),
        "local_ip": local_ip,
        "all_ips": all_ips,
        "platform": platform.system(),
        "platform_version": platform.version()[:40],
        "machine_arch": platform.machine(),
        "fingerprint": identity["fingerprint"][:12] + "...",
    }


# ── Resolucao de alvo ──────────────────────────────────────────────────────────

def resolve_target(target: str) -> dict | None:
    target = target.strip()
    normalized = normalize_code(target)

    # Codigo de acesso: somente numeros, 6 digitos (XXX-XXX)
    if len(normalized) == 6 and normalized.isdigit():
        formatted = f"{normalized[0:3]}-{normalized[3:6]}"
        return {
            "display": formatted,
            "method": "access_code",
            "code": formatted,
            "ip": None,
            "hostname": None,
            "status": "pending",
        }

    # IP direto
    try:
        ipaddress.ip_address(target)
        try:
            hostname = socket.gethostbyaddr(target)[0]
        except Exception:
            hostname = target
        return {
            "display": target,
            "method": "ip",
            "ip": target,
            "hostname": hostname,
            "status": "pending",
        }
    except ValueError:
        pass

    # Hostname
    try:
        ip = socket.gethostbyname(target)
        return {
            "display": target,
            "method": "hostname",
            "ip": ip,
            "hostname": target,
            "status": "pending",
        }
    except socket.gaierror:
        return {
            "display": target,
            "method": "hostname",
            "ip": None,
            "hostname": target,
            "status": "unresolved",
        }


def _get_own_hostnames() -> set:
    hostnames = {socket.gethostname(), socket.gethostname().lower(), socket.gethostname().upper()}
    try:
        hostnames.add(socket.gethostbyaddr(get_local_ip())[0])
    except Exception:
        pass
    return hostnames


def is_local_target(target: str) -> bool:
    """Verifica se o alvo (IP, hostname ou codigo) e a propria maquina."""
    local_ips = set(get_all_local_ips())
    own_hostnames = _get_own_hostnames()

    # IP
    try:
        ip = ipaddress.ip_address(target)
        return str(ip) in local_ips
    except ValueError:
        pass

    # Hostname
    clean = target.strip().lower()
    if clean in own_hostnames:
        return True
    try:
        resolved = socket.gethostbyname(clean)
        return resolved in local_ips
    except Exception:
        pass

    return False


def is_own_code(code: str) -> bool:
    """Verifica se o codigo de acesso e o da propria maquina."""
    try:
        identity = load_or_create_identity()
        return normalize_code(code) == normalize_code(identity.get("access_code", ""))
    except Exception:
        return False


def ping_host(ip: str, timeout: float = 1.0) -> bool:
    try:
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 1)
        return result.returncode == 0
    except Exception:
        return False


# ── Scan de rede ───────────────────────────────────────────────────────────────

class NetworkScanner:

    def __init__(self,
                 on_found: callable = None,
                 on_progress: callable = None,
                 on_done: callable = None,
                 max_workers: int = 80,
                 timeout: float = 0.4):
        self.on_found    = on_found
        self.on_progress = on_progress
        self.on_done     = on_done
        self.max_workers = max_workers
        self.timeout     = timeout

        self._stop_event = threading.Event()
        self._found: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop_event.clear()
        self._found = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        subnets = get_all_subnets()
        my_ips  = set(get_all_local_ips())

        targets = []
        for subnet in subnets:
            for i in range(1, 255):
                ip = f"{subnet}.{i}"
                if ip not in my_ips:
                    targets.append(ip)

        seen = set()
        unique_targets = []
        for ip in targets:
            if ip not in seen:
                seen.add(ip)
                unique_targets.append(ip)

        total = len(unique_targets)
        done_count = [0]
        semaphore = threading.Semaphore(self.max_workers)

        def check(ip):
            if self._stop_event.is_set():
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.timeout)
                result = s.connect_ex((ip, REMOTELINK_PORT))
                s.close()

                if result == 0 and not self._stop_event.is_set():
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except Exception:
                        hostname = ip

                    machine = {
                        "ip":       ip,
                        "hostname": hostname,
                        "method":   "scan",
                        "status":   "online",
                    }
                    with self._lock:
                        self._found.append(machine)

                    if self.on_found:
                        self.on_found(machine)
            except Exception:
                pass
            finally:
                with self._lock:
                    done_count[0] += 1
                    pct = done_count[0] / total if total else 1.0
                if self.on_progress:
                    self.on_progress(pct)
                semaphore.release()

        threads = []
        for ip in unique_targets:
            if self._stop_event.is_set():
                break
            semaphore.acquire()
            t = threading.Thread(target=check, args=(ip,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=self.timeout + 0.5)

        if self.on_done:
            self.on_done(list(self._found))


def scan_local_network(progress_callback=None) -> list[dict]:
    results = []
    done_event = threading.Event()

    def on_done(found):
        results.extend(found)
        done_event.set()

    scanner = NetworkScanner(
        on_progress=progress_callback,
        on_done=on_done,
        timeout=0.5,
    )
    scanner.start()
    done_event.wait(timeout=30)
    return results
