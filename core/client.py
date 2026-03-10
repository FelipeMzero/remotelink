"""
RemoteLink - Client (Viewer) Module
Dois sockets separados:
  - _frame_sock: recebe frames do servidor (leitura contínua)
  - _input_sock: envia input ao servidor  (escrita sob demanda)
Elimina race condition de leitura/escrita simultânea.
"""

import socket
import threading
import struct
import json
import time
import logging
import ipaddress
from typing import Callable, Optional

logger = logging.getLogger("remotelink.client")

FRAME_PORT      = 52340
INPUT_PORT      = 52341
PROTO_VER       = 1
CONNECT_TIMEOUT = 8.0
PROBE_TIMEOUT   = 3.0


def normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


# ── Probe ─────────────────────────────────────────────────────────────────────

def _recv_exact_s(sock: socket.socket, n: int, timeout: float) -> Optional[bytes]:
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
            if not chunk: return None
            buf += chunk
        except Exception: return None
    return buf


def probe_target(ip: str, port: int = FRAME_PORT,
                 timeout: float = PROBE_TIMEOUT) -> dict:
    base = {"ip": ip, "reachable": False}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))

        hello = json.dumps({
            "version": PROTO_VER, "access_code": "",
            "probe": True, "session_id": "",
        }).encode()
        s.sendall(struct.pack(">I", len(hello)) + hello)

        hdr = _recv_exact_s(s, 4, timeout)
        if not hdr: s.close(); return {**base, "error": "sem resposta"}
        n = struct.unpack(">I", hdr)[0]
        if not (0 < n < 65536): s.close(); return {**base, "error": "inválido"}
        raw = _recv_exact_s(s, n, timeout)
        s.close()
        if not raw: return {**base, "error": "dados incompletos"}
        resp = json.loads(raw)
        m = resp.get("machine", {})
        m["reachable"] = True
        m["ip"]        = ip
        return m
    except socket.timeout:  return {**base, "error": "timeout"}
    except ConnectionRefusedError: return {**base, "error": "recusado"}
    except Exception as e:  return {**base, "error": str(e)}


def resolve_hostname_to_ips(hostname: str) -> list[str]:
    ips, seen = [], set()
    try:
        for r in socket.getaddrinfo(hostname, FRAME_PORT,
                                    socket.AF_INET, socket.SOCK_STREAM):
            ip = r[4][0]
            if ip not in seen:
                seen.add(ip); ips.append(ip)
    except Exception:
        try:
            ip = socket.gethostbyname(hostname)
            ips.append(ip)
        except Exception: pass
    return ips


def probe_hostname(hostname: str) -> dict:
    for ip in resolve_hostname_to_ips(hostname):
        r = probe_target(ip)
        if r.get("reachable"):
            r.setdefault("hostname", hostname)
            return r
    return {"reachable": False, "hostname": hostname,
            "error": "Nenhum IP respondeu"}


# ── RemoteLinkClient ──────────────────────────────────────────────────────────

class RemoteLinkClient:
    """
    Dois sockets dedicados:
      _frame_sock  → recebe frames (thread RL-Recv lê continuamente)
      _input_sock  → envia input  (thread principal escreve sob demanda)
    Lock protege escrita no _input_sock (múltiplos botões simultâneos).
    """

    def __init__(self,
                 on_frame:         Callable = None,
                 on_connected:     Callable = None,
                 on_disconnected:  Callable = None,
                 on_status_change: Callable = None,
                 on_error:         Callable = None):
        self.on_frame         = on_frame
        self.on_connected     = on_connected
        self.on_disconnected  = on_disconnected
        self.on_status_change = on_status_change
        self.on_error         = on_error

        self._frame_sock: Optional[socket.socket] = None
        self._input_sock: Optional[socket.socket] = None
        self._input_lock  = threading.Lock()
        self._running     = False
        self._connected   = False
        self.remote_info: Optional[dict] = None
        self._session_id  = ""

    # ── Connect ───────────────────────────────────────────────────────────

    def connect(self, ip: str, port: int = FRAME_PORT,
                access_code: str = "",
                local_access_code: str = "") -> bool:
        self._notify_status("connecting")
        try:
            # ── Canal de frames ────────────────────────────────────────────
            fsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            fsock.settimeout(CONNECT_TIMEOUT)
            fsock.connect((ip, port))

            hello = json.dumps({
                "version":     PROTO_VER,
                "access_code": normalize_code(access_code),
                "viewer_code": normalize_code(local_access_code),
                "probe":       False,
                "session_id":  "",
            }).encode()
            self._send_raw(fsock, hello)

            resp_raw = self._recv_raw(fsock)
            if not resp_raw:
                fsock.close()
                self._notify_error("Sem resposta do servidor")
                return False

            resp = json.loads(resp_raw)
            if resp.get("status") != "accepted":
                reason = resp.get("reason", "Conexão rejeitada")
                fsock.close()
                self._notify_error(reason)
                return False

            self.remote_info = resp.get("machine", {})
            self._session_id = resp.get("session_id", "")
            input_port       = resp.get("input_port", port + 1)

            fsock.settimeout(None)
            self._frame_sock = fsock

            # ── Canal de input ─────────────────────────────────────────────
            isock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            isock.settimeout(CONNECT_TIMEOUT)
            isock.connect((ip, input_port))

            ihello = json.dumps({
                "session_id": self._session_id,
            }).encode()
            self._send_raw(isock, ihello)

            iresp_raw = self._recv_raw(isock)
            if not iresp_raw or json.loads(iresp_raw).get("status") != "ok":
                logger.warning("Canal de input rejeitado — continuando sem input")
                isock.close()
                isock = None
            else:
                isock.settimeout(None)
                # Desabilita Nagle para latência mínima no input
                isock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            self._input_sock = isock
            self._running    = True
            self._connected  = True

            # Thread dedicada para recepção de frames
            threading.Thread(target=self._recv_loop,
                             daemon=True, name="RL-Recv").start()

            self._notify_status("connected")
            if self.on_connected:
                self.on_connected(self.remote_info)

            logger.info(f"Conectado a {ip} — session={self._session_id} "
                        f"input={'ok' if isock else 'FALHOU'}")
            return True

        except socket.timeout:
            self._notify_error("Tempo de conexão esgotado")
        except ConnectionRefusedError:
            self._notify_error("Conexão recusada — RemoteLink está rodando no alvo?")
        except Exception as e:
            self._notify_error(str(e))
        return False

    def disconnect(self):
        self._running    = False
        self._connected  = False
        if self._input_sock:
            try:
                self._send_ctrl({"cmd": "disconnect"})
                self._input_sock.close()
            except Exception: pass
            self._input_sock = None
        if self._frame_sock:
            try: self._frame_sock.close()
            except Exception: pass
            self._frame_sock = None
        self._notify_status("disconnected")
        if self.on_disconnected:
            self.on_disconnected()

    def is_connected(self) -> bool:
        return self._connected

    # ── Input API ─────────────────────────────────────────────────────────

    def send_mouse_move(self, x, y):
        self._send_input({"type": "mouse_move", "x": x, "y": y})

    def send_mouse_click(self, x, y, button="left"):
        self._send_input({"type": "mouse_click", "x": x, "y": y, "button": button})

    def send_mouse_dblclick(self, x, y):
        self._send_input({"type": "mouse_dblclick", "x": x, "y": y})

    def send_mouse_scroll(self, x, y, delta):
        self._send_input({"type": "mouse_scroll", "x": x, "y": y, "delta": delta})

    def send_key_press(self, key: str):
        self._send_input({"type": "key_press", "key": key})

    def send_hotkey(self, *keys):
        self._send_input({"type": "key_hotkey", "keys": list(keys)})

    def send_text(self, text: str):
        self._send_input({"type": "type_text", "text": text})

    # ── Internos ──────────────────────────────────────────────────────────

    def _recv_loop(self):
        """Thread dedicada: lê frames do _frame_sock continuamente."""
        sock = self._frame_sock
        try:
            while self._running and sock:
                # Cabeçalho: tipo(1) + tamanho(4) + ts(4) = 9 bytes
                hdr = self._recv_exact_s(sock, 9)
                if not hdr:
                    break
                msg_type, msg_len, ts = struct.unpack(">BII", hdr)
                if msg_len == 0:
                    continue
                if msg_len > 30 * 1024 * 1024:
                    logger.warning(f"Frame enorme: {msg_len}")
                    break
                data = self._recv_exact_s(sock, msg_len)
                if not data:
                    break
                if msg_type == 0x01 and self.on_frame:
                    self.on_frame(data, ts)
        except Exception as e:
            logger.debug(f"recv_loop: {e}")
        finally:
            self._connected = False
            if self._running:
                self._running = False
                self._notify_status("disconnected")
                if self.on_disconnected:
                    self.on_disconnected()

    def _send_input(self, event: dict):
        """Envia evento pelo canal de input dedicado (thread-safe)."""
        if not self._connected:
            return
        sock = self._input_sock
        if not sock:
            logger.debug(f"input_sock indisponível — evento descartado: {event}")
            return
        try:
            data = json.dumps(event, separators=(",", ":")).encode()
            hdr  = struct.pack(">BI", 0x02, len(data))
            with self._input_lock:
                sock.sendall(hdr + data)
        except Exception as e:
            logger.warning(f"_send_input error: {e}")
            self._connected = False

    def _send_ctrl(self, msg: dict):
        sock = self._input_sock
        if not sock:
            return
        try:
            data = json.dumps(msg).encode()
            hdr  = struct.pack(">BI", 0x03, len(data))
            sock.sendall(hdr + data)
        except Exception:
            pass

    def _send_raw(self, sock: socket.socket, data: bytes):
        sock.sendall(struct.pack(">I", len(data)) + data)

    def _recv_raw(self, sock: socket.socket) -> Optional[bytes]:
        hdr = self._recv_exact_s(sock, 4)
        if not hdr: return None
        n = struct.unpack(">I", hdr)[0]
        if n > 10 * 1024 * 1024: return None
        return self._recv_exact_s(sock, n)

    def _recv_exact_s(self, sock: socket.socket, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk: return None
                buf += chunk
            except Exception: return None
        return buf

    def _notify_status(self, s: str):
        if self.on_status_change:
            try: self.on_status_change(s)
            except Exception: pass

    def _notify_error(self, msg: str):
        logger.error(f"Client: {msg}")
        if self.on_error:
            try: self.on_error(msg)
            except Exception: pass
