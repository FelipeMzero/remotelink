"""
RemoteLink - Machine Identity, Open Ports, STUN, UPnP & External Relay
- Codigo de acesso somente numeros (formato XXX-XXX) — funciona em LAN, VPN e Rede Externa
- Codigo Externo compacto (RL-XXXX-XXXX-XXXX) e formato AnyDesk (XXX-XXX@IP:PORTA)
- Multi-Portas Abertas (52340, 7070, 6568, 8080, 8443, 33890, 443, 80)
- STUN UDP ultrarrapido (stun.l.google.com:19302) + UPnP IGD automatico
- Cloud Rendezvous + Outbound TCP Relay Bridge (funciona mesmo atras de CGNAT/Firewall)
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
import time
import struct
import base64
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Callable

IDENTITY_FILE    = Path.home() / ".remotelink" / "identity.json"
PEERS_CACHE_FILE = Path.home() / ".remotelink" / "peers_cache.json"
REMOTELINK_PORT  = 52340
INPUT_PORT       = 52341

# Portas comuns/abertas tentadas pelo servidor e cliente (estilo AnyDesk 7070/6568/8080/443/80)
CANDIDATE_OPEN_PORTS = [52340, 7070, 6568, 8080, 8443, 33890, 443, 80]

_PUBLIC_IP_CACHE = {"ip": None, "ts": 0.0}
_PUBLIC_IP_LOCK  = threading.Lock()

_B32_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_B32_MAP      = {c: i for i, c in enumerate(_B32_ALPHABET)}


# ── Descoberta de IPs (LAN, VPN e WAN via STUN / HTTP) ────────────────────────

def get_all_local_ips() -> list[str]:
    ips = set()
    try:
        for target in ("8.8.8.8", "1.1.1.1"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1.0)
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
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(
                    ["ipconfig"], capture_output=True, text=True,
                    timeout=3, startupinfo=startupinfo
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


def get_vpn_ips() -> list[str]:
    """Detecta IPs de VPNs / Redes Overlay (Radmin VPN 26.x, Tailscale 100.x, Hamachi 25.x, ZeroTier)."""
    vpn = []
    for ip in get_all_local_ips():
        if ip.startswith(("26.", "100.", "25.", "172.")):
            vpn.append(ip)
    return vpn


def discover_stun_ip(timeout: float = 1.2) -> Optional[str]:
    """Obtém o IP público em <100ms via protocolo STUN UDP (RFC 5389)."""
    stun_servers = [
        ("stun.l.google.com", 19302),
        ("stun1.l.google.com", 19302),
        ("stun.cloudflare.com", 3478),
    ]
    magic_cookie = 0x2112A442
    tx_id = os.urandom(12)
    req = struct.pack(">HHI", 0x0001, 0, magic_cookie) + tx_id

    for host, port in stun_servers:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(req, (host, port))
            data, _ = sock.recvfrom(2048)
            if len(data) < 20:
                continue
            msg_type, msg_len, cookie = struct.unpack(">HHI", data[:8])
            if msg_type != 0x0101 or cookie != magic_cookie:
                continue
            pos = 20
            while pos + 4 <= len(data):
                attr_type, attr_len = struct.unpack(">HH", data[pos:pos + 4])
                val = data[pos + 4 : pos + 4 + attr_len]
                # XOR-MAPPED-ADDRESS (0x0020) ou MAPPED-ADDRESS (0x0001)
                if attr_type == 0x0020 and len(val) >= 8 and val[1] == 0x01:
                    xip = struct.unpack(">I", val[4:8])[0] ^ magic_cookie
                    return socket.inet_ntoa(struct.pack(">I", xip))
                elif attr_type == 0x0001 and len(val) >= 8 and val[1] == 0x01:
                    return socket.inet_ntoa(val[4:8])
                pos += 4 + ((attr_len + 3) & ~3)
        except Exception:
            pass
        finally:
            sock.close()
    return None


def get_public_ip(force_refresh: bool = False, timeout: float = 2.0) -> Optional[str]:
    """Obtém o IP público (WAN) via STUN UDP ultrarrápido ou fallback HTTP."""
    with _PUBLIC_IP_LOCK:
        now = time.time()
        if not force_refresh and _PUBLIC_IP_CACHE["ip"] and (now - _PUBLIC_IP_CACHE["ts"] < 300):
            return _PUBLIC_IP_CACHE["ip"]

    # 1. Tenta STUN UDP primeiro (~50ms)
    stun_ip = discover_stun_ip(timeout=1.0)
    if stun_ip:
        with _PUBLIC_IP_LOCK:
            _PUBLIC_IP_CACHE["ip"] = stun_ip
            _PUBLIC_IP_CACHE["ts"] = time.time()
        return stun_ip

    # 2. Fallback HTTP
    endpoints = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://icanhazip.com",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RemoteLink/1.2"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ip_txt = resp.read().decode("utf-8", errors="ignore").strip()
                ipaddress.ip_address(ip_txt)
                with _PUBLIC_IP_LOCK:
                    _PUBLIC_IP_CACHE["ip"] = ip_txt
                    _PUBLIC_IP_CACHE["ts"] = time.time()
                return ip_txt
        except Exception:
            continue
    return _PUBLIC_IP_CACHE.get("ip")


def get_all_subnets() -> list[str]:
    subnets = set()
    for ip in get_all_local_ips():
        parts = ip.split(".")
        if len(parts) == 4:
            subnets.add(".".join(parts[:3]))
    return list(subnets)


# ── Código Externo Compacto (Codifica IP + Porta + Código XXX-XXX) ────────────

def _b32_encode(data: bytes) -> str:
    bits = 0
    val = 0
    out = []
    for b in data:
        val = (val << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_B32_ALPHABET[(val >> bits) & 0x1F])
    if bits > 0:
        out.append(_B32_ALPHABET[(val << (5 - bits)) & 0x1F])
    return "".join(out)


def _b32_decode(text: str) -> Optional[bytes]:
    bits = 0
    val = 0
    out = bytearray()
    for c in text.upper():
        if c not in _B32_MAP:
            return None
        val = (val << 5) | _B32_MAP[c]
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((val >> bits) & 0xFF)
    return bytes(out)


def encode_external_code(access_code: str, ip: str, port: int = REMOTELINK_PORT) -> str:
    try:
        ip_bytes = socket.inet_aton(ip)
        code_num = int(normalize_code(access_code) or "0") & 0xFFFFF
        if port == REMOTELINK_PORT:
            chk = (sum(ip_bytes) + (code_num & 0xFF) + ((code_num >> 8) & 0xFF)) & 0x07
            packed24 = (0 << 23) | (code_num << 3) | chk
            raw = ip_bytes + packed24.to_bytes(3, "big")
            b32 = _b32_encode(raw)
            return f"RL-{b32[0:4]}-{b32[4:8]}-{b32[8:12]}"
        else:
            chk = (sum(ip_bytes) + (port & 0xFF) + (code_num & 0xFF)) & 0x07
            packed24 = (1 << 23) | (code_num << 3) | chk
            raw = ip_bytes + struct.pack(">H", port) + packed24.to_bytes(3, "big")
            b32 = _b32_encode(raw)
            return f"RL-{b32[0:5]}-{b32[5:10]}-{b32[10:]}"
    except Exception:
        return f"{access_code}@{ip}" if port == REMOTELINK_PORT else f"{access_code}@{ip}:{port}"


def decode_external_code(token: str) -> Optional[dict]:
    clean = token.strip().upper()
    if clean.startswith("RL-"):
        clean = clean[3:]
    clean = re.sub(r'[^A-Z2-9]', '', clean)
    raw = _b32_decode(clean)
    if not raw:
        return None
    try:
        if len(raw) == 7:
            ip = socket.inet_ntoa(raw[0:4])
            packed24 = int.from_bytes(raw[4:7], "big")
            if ((packed24 >> 23) & 1) != 0:
                return None
            code_num = (packed24 >> 3) & 0xFFFFF
            chk = packed24 & 0x07
            exp_chk = (sum(raw[0:4]) + (code_num & 0xFF) + ((code_num >> 8) & 0xFF)) & 0x07
            if chk != exp_chk or code_num > 999999:
                return None
            code_str = f"{code_num:06d}"
            return {"ip": ip, "port": REMOTELINK_PORT, "code": f"{code_str[:3]}-{code_str[3:]}"}
        elif len(raw) == 9:
            ip = socket.inet_ntoa(raw[0:4])
            port = struct.unpack(">H", raw[4:6])[0]
            packed24 = int.from_bytes(raw[6:9], "big")
            if ((packed24 >> 23) & 1) != 1:
                return None
            code_num = (packed24 >> 3) & 0xFFFFF
            chk = packed24 & 0x07
            exp_chk = (sum(raw[0:4]) + (port & 0xFF) + (code_num & 0xFF)) & 0x07
            if chk != exp_chk or code_num > 999999:
                return None
            code_str = f"{code_num:06d}"
            return {"ip": ip, "port": port, "code": f"{code_str[:3]}-{code_str[3:]}"}
    except Exception:
        pass
    return None


# ── UPnP IGD Port Forwarding + Firewall ───────────────────────────────────────

class UPnPManager:
    @staticmethod
    def _discover_control_url(timeout: float = 1.8) -> tuple[Optional[str], Optional[str]]:
        ssdp_msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            "MAN: \"ssdp:discover\"\r\n"
            "MX: 2\r\n"
            "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
        ).encode("ascii")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        location = None
        try:
            sock.sendto(ssdp_msg, ("239.255.255.250", 1900))
            while True:
                data, _ = sock.recvfrom(4096)
                txt = data.decode("utf-8", errors="ignore")
                m = re.search(r"(?i)^LOCATION:\s*(http[^\r\n]+)", txt, re.M)
                if m:
                    location = m.group(1).strip()
                    break
        except Exception:
            pass
        finally:
            sock.close()

        if not location:
            return None, None

        try:
            with urllib.request.urlopen(location, timeout=timeout) as resp:
                xml_data = resp.read().decode("utf-8", errors="ignore")
            root = ET.fromstring(xml_data)
            for service in root.iter():
                if service.tag.endswith("service"):
                    stype = ""
                    ctrl_url = ""
                    for child in service:
                        if child.tag.endswith("serviceType") and child.text:
                            stype = child.text.strip()
                        elif child.tag.endswith("controlURL") and child.text:
                            ctrl_url = child.text.strip()
                    if ("WANIPConnection" in stype or "WANPPPConnection" in stype) and ctrl_url:
                        full_url = urllib.parse.urljoin(location, ctrl_url)
                        return full_url, stype
        except Exception:
            pass
        return None, None

    @staticmethod
    def _soap_call(control_url: str, service_type: str, action: str, args_xml: str, timeout: float = 2.0) -> Optional[str]:
        body = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{service_type}">'
            f'{args_xml}'
            f'</u:{action}></s:Body></s:Envelope>'
        ).encode("utf-8")
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "Content-Length": str(len(body)),
        }
        req = urllib.request.Request(control_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    @classmethod
    def forward_ports(cls, ports: list[int] | tuple[int, ...] = tuple(CANDIDATE_OPEN_PORTS)) -> dict:
        local_ip = get_local_ip()
        ctrl_url, stype = cls._discover_control_url()
        if not ctrl_url or not stype:
            return {"ok": False, "mapped_ports": [], "external_ip": None, "local_ip": local_ip}

        ext_ip = None
        try:
            resp_xml = cls._soap_call(ctrl_url, stype, "GetExternalIPAddress", "")
            if resp_xml:
                m = re.search(r"<NewExternalIPAddress>([^<]+)</NewExternalIPAddress>", resp_xml)
                if m:
                    ext_ip = m.group(1).strip()
        except Exception:
            pass

        mapped = []
        for p in ports:
            args = (
                "<NewRemoteHost></NewRemoteHost>"
                f"<NewExternalPort>{p}</NewExternalPort>"
                "<NewProtocol>TCP</NewProtocol>"
                f"<NewInternalPort>{p}</NewInternalPort>"
                f"<NewInternalClient>{local_ip}</NewInternalClient>"
                "<NewEnabled>1</NewEnabled>"
                f"<NewPortMappingDescription>RemoteLink-{p}</NewPortMappingDescription>"
                "<NewLeaseDuration>0</NewLeaseDuration>"
            )
            try:
                cls._soap_call(ctrl_url, stype, "AddPortMapping", args)
                mapped.append(p)
            except Exception:
                pass

        return {
            "ok": len(mapped) > 0,
            "mapped_ports": mapped,
            "external_ip": ext_ip,
            "local_ip": local_ip,
        }


def ensure_firewall_rules(ports: list[int] | tuple[int, ...] = tuple(CANDIDATE_OPEN_PORTS)):
    if platform.system() != "Windows":
        return
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        port_list = ",".join(str(p) for p in ports)
        subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=RemoteLink MultiPort TCP", "dir=in", "action=allow",
                "protocol=TCP", f"localport={port_list}"
            ],
            capture_output=True, timeout=3, startupinfo=startupinfo
        )
    except Exception:
        pass


# ── Outbound TCP Relay Bridge (Funciona 100% mesmo sob CGNAT / Sem Portas) ───

class MQTTRelaySocket:
    """
    Cliente MQTT v3.1.1 binário minimalista sobre TCP puro (zero dependências externas).
    Permite que Host e Viewer troquem pacotes de vídeo e input através de conexões
    TCP de saída (Outbound), atravessando qualquer NAT/CGNAT/Firewall sem abrir portas.
    """

    BROKERS = [
        ("test.mosquitto.org", 1883),
        ("broker.emqx.io", 1883),
    ]

    def __init__(self, host: str = "test.mosquitto.org", port: int = 1883,
                 on_message: Callable = None):
        self.host = host
        self.port = port
        self.on_message = on_message
        self.sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self.connected = False

    @staticmethod
    def _enc_len(x: int) -> bytes:
        out = bytearray()
        while True:
            b = x % 128
            x //= 128
            if x > 0:
                b |= 0x80
            out.append(b)
            if x == 0:
                break
        return bytes(out)

    def connect(self, timeout: float = 3.5) -> bool:
        brokers = [(self.host, self.port)] + [b for b in self.BROKERS if b != (self.host, self.port)]
        for bhost, bport in brokers:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.connect((bhost, bport))
                cid = ("rl_" + uuid.uuid4().hex[:12]).encode("ascii")
                vhdr = b"\x00\x04MQTT\x04\x02\x00\x3c" + struct.pack(">H", len(cid)) + cid
                s.sendall(b"\x10" + self._enc_len(len(vhdr)) + vhdr)
                resp = s.recv(4)
                if not resp or resp[0] != 0x20 or resp[3] != 0:
                    s.close()
                    continue
                s.settimeout(None)
                self.host = bhost
                self.port = bport
                self.sock = s
                self.connected = True
                if self.on_message:
                    threading.Thread(target=self._reader_loop, daemon=True, name="RL-MQTTRead").start()
                    threading.Thread(target=self._ping_loop, daemon=True, name="RL-MQTTPing").start()
                return True
            except Exception:
                pass
        return False

    def _reader_loop(self):
        while self.connected and self.sock:
            item = self.read_next_publish()
            if item is None:
                if not self.connected:
                    break
                continue
            topic, payload = item
            if self.on_message:
                try:
                    self.on_message(topic, payload)
                except Exception:
                    pass

    def _ping_loop(self):
        while self.connected and self.sock:
            for _ in range(40):
                if not self.connected:
                    return
                time.sleep(0.5)
            self.ping()

    def subscribe(self, topic: str) -> bool:
        if not self.sock:
            return False
        try:
            tb = topic.encode("utf-8")
            pl = struct.pack(">H", 1) + struct.pack(">H", len(tb)) + tb + b"\x00"
            with self._send_lock:
                self.sock.sendall(b"\x82" + self._enc_len(len(pl)) + pl)
            return True
        except Exception:
            self.connected = False
            return False

    def publish(self, topic: str, payload: bytes) -> bool:
        if not self.sock or not self.connected:
            return False
        try:
            tb = topic.encode("utf-8")
            pl = struct.pack(">H", len(tb)) + tb + payload
            pkt = b"\x30" + self._enc_len(len(pl)) + pl
            with self._send_lock:
                self.sock.sendall(pkt)
            return True
        except Exception:
            self.connected = False
            return False

    def _recv_exact(self, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except Exception:
                return None
        return bytes(buf)

    def read_next_publish(self) -> Optional[tuple[str, bytes]]:
        if not self.sock:
            return None
        while self.connected:
            hdr1 = self._recv_exact(1)
            if not hdr1:
                self.connected = False
                return None
            pkt_type = hdr1[0]
            # Decode varint length
            mult = 1
            rem_len = 0
            while True:
                b = self._recv_exact(1)
                if not b:
                    self.connected = False
                    return None
                rem_len += (b[0] & 0x7F) * mult
                if (b[0] & 0x80) == 0:
                    break
                mult *= 128

            body = self._recv_exact(rem_len) if rem_len > 0 else b""
            if body is None:
                self.connected = False
                return None

            if (pkt_type & 0xF0) == 0x30 and len(body) >= 2:
                tlen = struct.unpack(">H", body[:2])[0]
                topic = body[2 : 2 + tlen].decode("utf-8", errors="ignore")
                pos = 2 + tlen
                qos = (pkt_type >> 1) & 0x03
                if qos > 0:
                    pos += 2
                return topic, body[pos:]
        return None

    def ping(self):
        if self.sock and self.connected:
            try:
                with self._send_lock:
                    self.sock.sendall(b"\xc0\x00")
            except Exception:
                self.connected = False

    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


# ── Cloud Rendezvous & Signaling ──────────────────────────────────────────────

class CloudRegistry:
    BASE_URL = "https://ntfy.sh"

    @staticmethod
    def _topic_for_code(code: str, prefix: str = "dir") -> str:
        norm = normalize_code(code)
        digest = hashlib.sha256(f"remotelink-v2-{prefix}-{norm}".encode()).hexdigest()[:22]
        return f"rl_{prefix}_{digest}"

    @staticmethod
    def relay_topics_for_code(code: str) -> dict[str, str]:
        norm = normalize_code(code)
        digest = hashlib.sha256(f"remotelink-relay-v2-{norm}".encode()).hexdigest()[:20]
        return {
            "ctrl":         f"rl_r/{digest}/ctrl",
            "handshake":    f"rl_r/{digest}/hs",
            "frame":        f"rl_r/{digest}/frame",
            "input":        f"rl_r/{digest}/input",
            "audio_host":   f"rl_r/{digest}/ah",
            "audio_viewer": f"rl_r/{digest}/av",
        }

    @staticmethod
    def _cipher_payload(norm_code: str, raw_bytes: bytes) -> bytes:
        key = hashlib.sha256(f"rl-key-{norm_code}".encode()).digest()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw_bytes))

    @classmethod
    def publish_presence(cls, machine_info: dict, port: int = REMOTELINK_PORT,
                         active_ports: list[int] = None,
                         open_ports: list[int] = None,
                         upnp_ok: bool = False) -> bool:
        code = machine_info.get("access_code", "")
        norm = normalize_code(code)
        if len(norm) != 6:
            return False

        pub_ip = machine_info.get("public_ip") or get_public_ip()
        ports_list = open_ports or active_ports or [port]
        payload = {
            "v": 2,
            "code": f"{norm[:3]}-{norm[3:]}",
            "public_ip": pub_ip,
            "local_ip": machine_info.get("local_ip") or get_local_ip(),
            "all_ips": machine_info.get("all_ips") or get_all_local_ips(),
            "vpn_ips": get_vpn_ips(),
            "port": port,
            "ports": ports_list,
            "open_ports": ports_list,
            "hostname": machine_info.get("hostname", socket.gethostname()),
            "platform": machine_info.get("platform", platform.system()),
            "platform_version": machine_info.get("platform_version", ""),
            "upnp": upnp_ok,
            "ts": int(time.time()),
        }
        save_peer_cache(norm, payload)
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        enc = base64.urlsafe_b64encode(cls._cipher_payload(norm, raw)).decode("ascii")

        topic = cls._topic_for_code(norm, "dir")
        try:
            req = urllib.request.Request(
                f"{cls.BASE_URL}/{topic}",
                data=enc.encode("ascii"),
                headers={"User-Agent": "RemoteLink/1.2"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    @classmethod
    def lookup_code(cls, code: str, timeout: float = 3.0) -> Optional[dict]:
        norm = normalize_code(code)
        if len(norm) != 6:
            return None

        topic = cls._topic_for_code(norm, "dir")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    f"{cls.BASE_URL}/{topic}/json?poll=1&since=all",
                    headers={"User-Agent": "RemoteLink/1.2"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()

                for line in reversed(lines):
                    try:
                        ev = json.loads(line)
                        if ev.get("event") != "message":
                            continue
                        msg_b64 = ev.get("message", "")
                        raw = cls._cipher_payload(norm, base64.urlsafe_b64decode(msg_b64.encode("ascii")))
                        info = json.loads(raw.decode("utf-8"))
                        if normalize_code(info.get("code", "")) == norm:
                            save_peer_cache(norm, info)
                            return info
                    except Exception:
                        continue
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.25)

        return load_peer_cache(norm)

    @classmethod
    def send_reverse_request(cls, target_code: str, viewer_endpoints: list[str],
                             reverse_port: int, session_token: str) -> bool:
        norm = normalize_code(target_code)
        if len(norm) != 6:
            return False
        payload = {
            "cmd": "reverse_connect",
            "endpoints": viewer_endpoints,
            "port": reverse_port,
            "token": session_token,
            "ts": int(time.time()),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        enc = base64.urlsafe_b64encode(cls._cipher_payload(norm, raw)).decode("ascii")
        topic = cls._topic_for_code(norm, "sig")
        try:
            req = urllib.request.Request(
                f"{cls.BASE_URL}/{topic}",
                data=enc.encode("ascii"),
                headers={"User-Agent": "RemoteLink/1.2"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    @classmethod
    def poll_reverse_requests(cls, own_code: str, seen_ids: set, timeout: float = 2.5) -> list[dict]:
        norm = normalize_code(own_code)
        if len(norm) != 6:
            return []
        topic = cls._topic_for_code(norm, "sig")
        out = []
        try:
            req = urllib.request.Request(
                f"{cls.BASE_URL}/{topic}/json?poll=1&since=all",
                headers={"User-Agent": "RemoteLink/1.2"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()
            for line in lines[-5:]:
                try:
                    ev = json.loads(line)
                    msg_id = ev.get("id")
                    if not msg_id or msg_id in seen_ids or ev.get("event") != "message":
                        continue
                    seen_ids.add(msg_id)
                    raw = cls._cipher_payload(norm, base64.urlsafe_b64decode(ev["message"].encode("ascii")))
                    data = json.loads(raw.decode("utf-8"))
                    if data.get("cmd") == "reverse_connect":
                        out.append(data)
                except Exception:
                    continue
        except Exception:
            pass
        return out


def save_peer_cache(code_norm: str, info: dict):
    try:
        PEERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache = {}
        if PEERS_CACHE_FILE.exists():
            with open(PEERS_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        cache[code_norm] = info
        with open(PEERS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def load_peer_cache(code_norm: str) -> Optional[dict]:
    try:
        if PEERS_CACHE_FILE.exists():
            with open(PEERS_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get(code_norm)
    except Exception:
        pass
    return None


# ── Identidade da máquina ──────────────────────────────────────────────────────

def _get_mac_address() -> str:
    mac = uuid.getnode()
    return ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(0, 48, 8))


def _get_fingerprint() -> str:
    parts = [_get_mac_address(), socket.gethostname(),
             platform.system(), platform.machine()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def generate_access_code(fingerprint: str) -> str:
    h = hashlib.md5(fingerprint.encode()).hexdigest()
    chars = []
    for i in range(6):
        val = int(h[i * 2: i * 2 + 2], 16)
        chars.append(str(val % 10))
    return f"{''.join(chars[0:3])}-{''.join(chars[3:6])}"


def normalize_code(code: str) -> str:
    return re.sub(r'[^0-9]', '', code)


def _is_valid_code(code: str) -> bool:
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


def get_machine_info(fetch_public: bool = False) -> dict:
    identity = load_or_create_identity()
    all_ips = get_all_local_ips()
    local_ip = get_local_ip()
    vpn_ips = get_vpn_ips()
    public_ip = get_public_ip() if fetch_public else _PUBLIC_IP_CACHE.get("ip")
    target_ip = public_ip or (vpn_ips[0] if vpn_ips else local_ip)
    ext_code = encode_external_code(identity["access_code"], target_ip, REMOTELINK_PORT)
    return {
        "access_code": identity["access_code"],
        "external_code": ext_code,
        "hostname": socket.gethostname(),
        "local_ip": local_ip,
        "public_ip": public_ip,
        "vpn_ips": vpn_ips,
        "all_ips": all_ips,
        "platform": platform.system(),
        "platform_version": platform.version()[:40],
        "machine_arch": platform.machine(),
        "fingerprint": identity["fingerprint"][:12] + "...",
    }


# ── Resolucao de alvo (LAN + VPN + Portas Abertas + Rede Externa) ─────────────

def _split_host_port(addr: str) -> tuple[str, int]:
    addr = addr.strip()
    if ":" in addr and addr.count(":") == 1:
        host_part, port_part = addr.rsplit(":", 1)
        if port_part.isdigit():
            p = int(port_part)
            if 1 <= p <= 65535:
                return host_part.strip(), p
    return addr, REMOTELINK_PORT


def resolve_target(target: str) -> dict | None:
    target = target.strip()
    if not target:
        return None

    # 1. Token de Código Externo compacto (RL-XXXX-XXXX-XXXX)
    if target.upper().startswith("RL-"):
        decoded = decode_external_code(target)
        if decoded:
            return {
                "display": target.upper(),
                "method": "external_code",
                "code": decoded["code"],
                "ip": decoded["ip"],
                "port": decoded["port"],
                "hostname": decoded["ip"],
                "status": "pending",
            }

    # 2. Sintaxe estilo AnyDesk: CODIGO@IP ou CODIGO@HOSTNAME:PORTA
    if "@" in target:
        code_part, host_part = target.split("@", 1)
        norm_c = normalize_code(code_part)
        host, port = _split_host_port(host_part)
        if len(norm_c) == 6 and host:
            formatted_code = f"{norm_c[:3]}-{norm_c[3:]}"
            try:
                ipaddress.ip_address(host)
                resolved_ip = host
            except ValueError:
                try:
                    resolved_ip = socket.gethostbyname(host)
                except Exception:
                    resolved_ip = None
            return {
                "display": f"{formatted_code}@{host}",
                "method": "external_code",
                "code": formatted_code,
                "ip": resolved_ip,
                "port": port,
                "hostname": host,
                "status": "pending" if resolved_ip else "unresolved",
            }

    # 3. Codigo de acesso: somente numeros, 6 digitos (XXX-XXX)
    normalized = normalize_code(target)
    if len(normalized) == 6 and re.fullmatch(r'[\d\-\s]+', target):
        formatted = f"{normalized[0:3]}-{normalized[3:6]}"
        return {
            "display": formatted,
            "method": "access_code",
            "code": formatted,
            "ip": None,
            "port": REMOTELINK_PORT,
            "hostname": None,
            "status": "pending",
        }

    # 4. IP direto ou IP:PORTA (LAN, VPN ou Rede Externa WAN)
    host_only, port = _split_host_port(target)
    try:
        ip_obj = ipaddress.ip_address(host_only)
        try:
            hostname = socket.gethostbyaddr(host_only)[0]
        except Exception:
            hostname = host_only
        is_wan = not ip_obj.is_private and not ip_obj.is_loopback
        return {
            "display": target,
            "method": "external_ip" if is_wan else "ip",
            "ip": host_only,
            "port": port,
            "hostname": hostname,
            "status": "pending",
        }
    except ValueError:
        pass

    # 5. Hostname / DDNS ou Hostname:PORTA
    try:
        ip = socket.gethostbyname(host_only)
        return {
            "display": target,
            "method": "hostname",
            "ip": ip,
            "port": port,
            "hostname": host_only,
            "status": "pending",
        }
    except socket.gaierror:
        return {
            "display": target,
            "method": "hostname",
            "ip": None,
            "port": port,
            "hostname": host_only,
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
    host_only, _ = _split_host_port(target)
    local_ips = set(get_all_local_ips())
    own_hostnames = _get_own_hostnames()

    try:
        ip = ipaddress.ip_address(host_only)
        return str(ip) in local_ips
    except ValueError:
        pass

    clean = host_only.strip().lower()
    if clean in own_hostnames:
        return True
    try:
        resolved = socket.gethostbyname(clean)
        return resolved in local_ips
    except Exception:
        pass

    return False


def is_own_code(code: str) -> bool:
    try:
        identity = load_or_create_identity()
        return normalize_code(code) == normalize_code(identity.get("access_code", ""))
    except Exception:
        return False


def ping_host(ip: str, timeout: float = 1.0) -> bool:
    try:
        system = platform.system().lower()
        if system == "windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 1, startupinfo=startupinfo)
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 1)
        return result.returncode == 0
    except Exception:
        return False


# ── Scan de rede (Multi-Portas) ────────────────────────────────────────────────

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
                for test_port in (REMOTELINK_PORT, 7070, 6568, 8080):
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(self.timeout)
                    result = s.connect_ex((ip, test_port))
                    s.close()
                    if result == 0 and not self._stop_event.is_set():
                        try:
                            hostname = socket.gethostbyaddr(ip)[0]
                        except Exception:
                            hostname = ip
                        machine = {
                            "ip":       ip,
                            "port":     test_port,
                            "hostname": hostname,
                            "method":   "scan",
                            "status":   "online",
                        }
                        with self._lock:
                            self._found.append(machine)
                        if self.on_found:
                            self.on_found(machine)
                        break
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
            t.join(timeout=self.timeout + 1.5)

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
