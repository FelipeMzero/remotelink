"""
RemoteLink - Machine Identity & Network Discovery
- Código de acesso case-insensitive
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
import struct
import threading
from pathlib import Path

IDENTITY_FILE = Path.home() / ".remotelink" / "identity.json"
REMOTELINK_PORT = 52340


# ── Helpers de rede ────────────────────────────────────────────────────────────

def get_all_local_ips() -> list[str]:
    """
    Retorna TODOS os IPs locais da máquina (cabeado + WiFi + VPN).
    Ignora loopback e link-local (169.254.x.x).
    """
    ips = set()
    try:
        # Método principal: conecta UDP para descobrir IPs de saída
        for target in ("8.8.8.8", "1.1.1.1"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect((target, 80))
                ips.add(s.getsockname()[0])
                s.close()
            except Exception:
                pass

        # Método secundário: resolve todas as interfaces via gethostbyname_ex
        try:
            hostname = socket.gethostname()
            _, _, addr_list = socket.gethostbyname_ex(hostname)
            for addr in addr_list:
                ips.add(addr)
        except Exception:
            pass

        # Método terciário: socket.getaddrinfo
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                addr = info[4][0]
                if ":" not in addr:  # Ignora IPv6
                    ips.add(addr)
        except Exception:
            pass

    except Exception:
        pass

    # Filtra loopback e link-local
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
    """IP principal (primeira interface válida)."""
    ips = get_all_local_ips()
    # Prefere 192.168.x.x ou 10.x.x.x
    for ip in ips:
        if ip.startswith(("192.168.", "10.", "172.")):
            return ip
    return ips[0] if ips else "127.0.0.1"


def get_all_subnets() -> list[str]:
    """Retorna todos os prefixos /24 das interfaces locais."""
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
    """
    Gera código no formato XXX-XXX-XXX.
    Sem caracteres ambíguos: 0 O I 1 L
    Sempre maiúsculo — comparação é case-insensitive.
    """
    charset = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    h = hashlib.md5(fingerprint.encode()).hexdigest()
    chars = []
    for i in range(9):
        val = int(h[i * 2: i * 2 + 2], 16)
        chars.append(charset[val % len(charset)])
    return f"{chars[0:3]}-{''.join(chars[3:6])}-{''.join(chars[6:9])}"


def normalize_code(code: str) -> str:
    """Normaliza código: strip, uppercase, remove espaços."""
    return code.strip().upper().replace(" ", "")


def codes_match(a: str, b: str) -> bool:
    """Compara dois códigos de forma case-insensitive."""
    return normalize_code(a) == normalize_code(b)


def load_or_create_identity() -> dict:
    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if IDENTITY_FILE.exists():
        try:
            with open(IDENTITY_FILE) as f:
                data = json.load(f)
            if data.get("fingerprint") == _get_fingerprint():
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
    return {
        "access_code": identity["access_code"],
        "hostname": socket.gethostname(),
        "local_ip": get_local_ip(),
        "all_ips": get_all_local_ips(),
        "platform": platform.system(),
        "platform_version": platform.version()[:40],
        "machine_arch": platform.machine(),
        "fingerprint": identity["fingerprint"][:12] + "...",
    }


# ── Resolução de alvo ──────────────────────────────────────────────────────────

def resolve_target(target: str) -> dict | None:
    """
    Resolve um alvo (código, IP ou hostname) para info de conexão.
    Código é case-insensitive.
    """
    target = target.strip()
    normalized = normalize_code(target)

    # Código de acesso: XXX-XXX-XXX (com ou sem hífens, maiúsculo ou minúsculo)
    clean = normalized.replace("-", "")
    if len(clean) == 9 and clean.isalnum():
        # Reconstrói no formato correto
        formatted = f"{clean[0:3]}-{clean[3:6]}-{clean[6:9]}"
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

    # Hostname — tenta resolver
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


# ── Scan de rede — sem travar a UI ────────────────────────────────────────────

class NetworkScanner:
    """
    Scanner assíncrono que verifica TODAS as interfaces (cabeada + WiFi).
    Usa pool de threads com limite para não travar.
    Chama callbacks conforme vai encontrando — UI atualiza em tempo real.
    """

    def __init__(self,
                 on_found: callable = None,
                 on_progress: callable = None,
                 on_done: callable = None,
                 max_workers: int = 80,
                 timeout: float = 0.4):
        self.on_found    = on_found      # (machine_dict) -> None
        self.on_progress = on_progress   # (0.0 .. 1.0)   -> None
        self.on_done     = on_done       # (found_list)   -> None
        self.max_workers = max_workers
        self.timeout     = timeout

        self._stop_event = threading.Event()
        self._found: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self):
        """Inicia o scan em background."""
        self._stop_event.clear()
        self._found = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Para o scan."""
        self._stop_event.set()

    def _run(self):
        subnets = get_all_subnets()
        my_ips  = set(get_all_local_ips())

        # Monta lista total de IPs a verificar (todas as interfaces)
        targets = []
        for subnet in subnets:
            for i in range(1, 255):
                ip = f"{subnet}.{i}"
                if ip not in my_ips:
                    targets.append(ip)

        # Remove duplicatas mantendo ordem
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

        # Aguarda todos terminarem
        for t in threads:
            t.join(timeout=self.timeout + 0.5)

        if self.on_done:
            self.on_done(list(self._found))


# Compat com código antigo
def scan_local_network(progress_callback=None) -> list[dict]:
    """Versão síncrona para compatibilidade."""
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
