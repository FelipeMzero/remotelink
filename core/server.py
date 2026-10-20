"""
RemoteLink - Server (Host) Module
Dois sockets por sessão:
  - Porta 52340: canal de frames (servidor → cliente)
  - Porta 52341: canal de input  (cliente → servidor)
Injeção nativa via Win32 SendInput (como no AnyDesk.exe) com suporte a:
  - Arrastar e soltar (Mouse Down / Move / Up separados + coordenadas normalizadas 0..65535)
  - Teclado via Hardware Scancode + Virtual-Key (VK) + Unicode (KEYEVENTF_UNICODE)
  - Liberação automática de teclas/botões presos ao desconectar ou perder foco
  - Rede Externa: UPnP IGD automático, Cloud Rendezvous e Conexão Reversa (NAT Traversal)
"""

import socket
import threading
import struct
import json
import time
import platform
import io
import uuid
import logging
import ctypes
from typing import Callable, Optional

from core.identity import normalize_code

logger = logging.getLogger("remotelink.server")

FRAME_PORT  = 52340   # servidor envia frames aqui
INPUT_PORT  = 52341   # servidor recebe input aqui
PROTO_VER   = 1
FPS_TARGET  = 60
FRAME_TIME  = 1.0 / FPS_TARGET


# ── Motor Nativo Win32 SendInput (Idêntico à arquitetura do AnyDesk.exe) ──────

_IS_WIN = platform.system() == "Windows"

if _IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx",          wintypes.LONG),
            ("dy",          wintypes.LONG),
            ("mouseData",   wintypes.DWORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg",    wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    class _INPUT(ctypes.Structure):
        _fields_ = [
            ("type",  wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]

    INPUT_MOUSE    = 0
    INPUT_KEYBOARD = 1

    MOUSEEVENTF_MOVE        = 0x0001
    MOUSEEVENTF_LEFTDOWN    = 0x0002
    MOUSEEVENTF_LEFTUP      = 0x0004
    MOUSEEVENTF_RIGHTDOWN   = 0x0008
    MOUSEEVENTF_RIGHTUP     = 0x0010
    MOUSEEVENTF_MIDDLEDOWN  = 0x0020
    MOUSEEVENTF_MIDDLEUP    = 0x0040
    MOUSEEVENTF_XDOWN       = 0x0080
    MOUSEEVENTF_XUP         = 0x0100
    MOUSEEVENTF_WHEEL       = 0x0800
    MOUSEEVENTF_HWHEEL      = 0x1000
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    MOUSEEVENTF_ABSOLUTE    = 0x8000

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP       = 0x0002
    KEYEVENTF_UNICODE     = 0x0004
    KEYEVENTF_SCANCODE    = 0x0008

    SM_XVIRTUALSCREEN  = 76
    SM_YVIRTUALSCREEN  = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79


# Mapa completo de nomes simbólicos para Win32 Virtual-Key (VK)
_NAME_TO_VK = {
    "backspace": 0x08, "back": 0x08,
    "tab": 0x09,
    "enter": 0x0D, "return": 0x0D, "kp_enter": 0x0D,
    "shift": 0x10, "lshift": 0xA0, "shift_l": 0xA0, "rshift": 0xA1, "shift_r": 0xA1,
    "ctrl": 0x11, "control": 0x11, "lctrl": 0xA2, "control_l": 0xA2, "rctrl": 0xA3, "control_r": 0xA3,
    "alt": 0x12, "menu": 0x12, "lalt": 0xA4, "alt_l": 0xA4, "ralt": 0xA5, "alt_r": 0xA5,
    "pause": 0x13,
    "capslock": 0x14, "caps_lock": 0x14,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21, "page_up": 0x21, "prior": 0x21,
    "pagedown": 0x22, "page_down": 0x22, "next": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C, "prtscr": 0x2C, "print": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "super_l": 0x5B, "windows": 0x5B, "rwin": 0x5C, "super_r": 0x5C,
    "apps": 0x5D, "menu_key": 0x5D,
    "numlock": 0x90, "num_lock": 0x90,
    "scrolllock": 0x91, "scroll_lock": 0x91,
    "multiply": 0x6A, "kp_multiply": 0x6A,
    "add": 0x6B, "kp_add": 0x6B, "plus": 0xBB,
    "subtract": 0x6D, "kp_subtract": 0x6D,
    "decimal": 0x6E, "kp_decimal": 0x6E,
    "divide": 0x6F, "kp_divide": 0x6F,
    "semicolon": 0xBA, ";": 0xBA,
    "equal": 0xBB, "=": 0xBB,
    "comma": 0xBC, ",": 0xBC,
    "minus": 0xBD, "-": 0xBD,
    "period": 0xBE, ".": 0xBE,
    "slash": 0xBF, "/": 0xBF,
    "grave": 0xC0, "quoteleft": 0xC0, "`": 0xC0,
    "bracketleft": 0xDB, "[": 0xDB,
    "backslash": 0xDC, "\\": 0xDC,
    "bracketright": 0xDD, "]": 0xDD,
    "apostrophe": 0xDE, "quoteright": 0xDE, "'": 0xDE,
    **{f"num{i}": 0x60 + i for i in range(10)},
    **{f"kp_{i}": 0x60 + i for i in range(10)},
    **{f"f{i}": 0x70 + i - 1 for i in range(1, 25)},
    **{chr(c): c for c in range(ord('0'), ord('9') + 1)},
    **{chr(c).lower(): c for c in range(ord('A'), ord('Z') + 1)},
}

_EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # PageUp/Down, End, Home, Arrows
    0x2C, 0x2D, 0x2E,                                # PrintScreen, Insert, Delete
    0x5B, 0x5C, 0x5D,                                # LWin, RWin, Apps
    0x6F, 0x90,                                      # Numpad Divide, NumLock
    0xA3, 0xA5,                                      # RCtrl, RAlt
}


class Win32InputInjector:
    """
    Injetor de mouse e teclado de baixíssima latência via API nativa Win32 SendInput
    com fallback automático para keybd_event / mouse_event / SetCursorPos.
    Suporta coordenadas absolutas normalizadas no Virtual Desktop, arrastar e soltar,
    scancodes de hardware, Unicode e limpeza automática de teclas presas.
    """

    def __init__(self):
        self._held_vks: set[tuple[int, int, bool]] = set()
        self._held_btns: set[str] = set()
        self._lock = threading.Lock()
        try:
            _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
            _user32.SendInput.restype  = wintypes.UINT
            _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
            _user32.MapVirtualKeyW.restype  = wintypes.UINT
            _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
            _user32.VkKeyScanW.restype  = ctypes.c_short
        except Exception:
            pass

    def _to_virtual_abs(self, px: int, py: int) -> tuple[int, int]:
        vx = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = max(1, _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        vh = max(1, _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        abs_x = int(((px - vx) * 65535) / max(1, vw - 1))
        abs_y = int(((py - vy) * 65535) / max(1, vh - 1))
        return max(0, min(65535, abs_x)), max(0, min(65535, abs_y))

    def _send_mouse_raw(self, flags: int, ax: int = 0, ay: int = 0, data: int = 0,
                        px: Optional[int] = None, py: Optional[int] = None):
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = ax
        inp.union.mi.dy = ay
        inp.union.mi.mouseData = data & 0xFFFFFFFF
        inp.union.mi.dwFlags = flags
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = 0
        sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        if not sent:
            if px is not None and py is not None and (flags & MOUSEEVENTF_MOVE):
                try:
                    _user32.SetCursorPos(int(px), int(py))
                except Exception:
                    pass
            btn_flags = flags & ~(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)
            if btn_flags:
                try:
                    _user32.mouse_event(btn_flags, 0, 0, data & 0xFFFFFFFF, 0)
                except Exception:
                    pass

    def _send_key_raw(self, vk: int, scan: int, flags: int):
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk & 0xFFFF
        inp.union.ki.wScan = scan & 0xFFFF
        inp.union.ki.dwFlags = flags
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = 0
        sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        if not sent and vk > 0:
            try:
                kb_flags = (KEYEVENTF_EXTENDEDKEY if (flags & KEYEVENTF_EXTENDEDKEY) else 0) | (
                    KEYEVENTF_KEYUP if (flags & KEYEVENTF_KEYUP) else 0
                )
                _user32.keybd_event(vk & 0xFF, scan & 0xFF, kb_flags, 0)
            except Exception:
                pass

    def mouse_move(self, x: int, y: int):
        ax, ay = self._to_virtual_abs(x, y)
        self._send_mouse_raw(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            ax, ay, px=x, py=y
        )

    def mouse_click(self, x: int, y: int, button: str, state: str):
        ax, ay = self._to_virtual_abs(x, y)
        move_flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        is_down = (state == "down")

        btn_map = {
            "left":   (MOUSEEVENTF_LEFTDOWN,   MOUSEEVENTF_LEFTUP),
            "right":  (MOUSEEVENTF_RIGHTDOWN,  MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }
        down_flag, up_flag = btn_map.get(button, btn_map["left"])
        act_flag = down_flag if is_down else up_flag

        with self._lock:
            if is_down:
                self._held_btns.add(button)
            else:
                self._held_btns.discard(button)

        self._send_mouse_raw(move_flags | act_flag, ax, ay, px=x, py=y)

    def mouse_scroll(self, x: int, y: int, delta: int, dx: int = 0):
        ax, ay = self._to_virtual_abs(x, y)
        self._send_mouse_raw(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            ax, ay, px=x, py=y
        )
        if delta:
            wheel_amount = int(delta) * 40 if abs(delta) <= 10 else int(delta)
            self._send_mouse_raw(MOUSEEVENTF_WHEEL, 0, 0, wheel_amount)
        if dx:
            hwheel_amount = int(dx) * 40 if abs(dx) <= 10 else int(dx)
            self._send_mouse_raw(MOUSEEVENTF_HWHEEL, 0, 0, hwheel_amount)

    def key_event(self, is_up: bool, key: str = "", vk: int = 0,
                  scan: int = 0, char: str = "", extended: bool = False):
        key_clean = (key or "").strip().lower()

        # Caractere Unicode acentuado / internacional (ex: ç, ã, é, ô)
        if char and len(char) == 1 and ord(char) > 127:
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if is_up else 0)
            self._send_key_raw(0, ord(char), flags)
            return

        # Se key_clean está na tabela de teclas nomeadas (enter, backspace, space, setas, etc.), prioriza
        mapped_vk = _NAME_TO_VK.get(key_clean, 0) if key_clean else 0
        if not vk or (mapped_vk and key_clean not in ("", "??")):
            if mapped_vk:
                vk = mapped_vk

        if not vk and key_clean and len(key_clean) == 1:
            res = _user32.VkKeyScanW(ord(key_clean))
            if res != -1 and (res & 0xFF) != 0xFF:
                vk = res & 0xFF

        if not vk and char and len(char) == 1 and ord(char) >= 32:
            res = _user32.VkKeyScanW(ord(char))
            if res != -1 and (res & 0xFF) != 0xFF:
                vk = res & 0xFF
            else:
                flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if is_up else 0)
                self._send_key_raw(0, ord(char), flags)
                return

        if not vk:
            return

        if not scan:
            scan = _user32.MapVirtualKeyW(vk, 0)

        is_ext = bool(extended or (vk in _EXTENDED_VKS))
        flags = (KEYEVENTF_EXTENDEDKEY if is_ext else 0) | (KEYEVENTF_KEYUP if is_up else 0)

        with self._lock:
            if not is_up:
                self._held_vks.add((vk, scan, is_ext))
            else:
                self._held_vks = {item for item in self._held_vks if item[0] != vk}

        self._send_key_raw(vk, scan, flags)

    def type_text(self, text: str):
        for ch in text:
            code = ord(ch)
            if ch == "\n":
                self.key_event(False, vk=0x0D)
                self.key_event(True, vk=0x0D)
            elif ch == "\t":
                self.key_event(False, vk=0x09)
                self.key_event(True, vk=0x09)
            else:
                self._send_key_raw(0, code, KEYEVENTF_UNICODE)
                self._send_key_raw(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)

    def release_all(self):
        """Solta imediatamente todas as teclas e botões de mouse retidos."""
        with self._lock:
            vks = list(self._held_vks)
            btns = list(self._held_btns)
            self._held_vks.clear()
            self._held_btns.clear()

        for vk, scan, is_ext in vks:
            flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if is_ext else 0)
            self._send_key_raw(vk, scan, flags)

        btn_up_map = {
            "left": MOUSEEVENTF_LEFTUP,
            "right": MOUSEEVENTF_RIGHTUP,
            "middle": MOUSEEVENTF_MIDDLEUP,
        }
        for b in btns:
            if b in btn_up_map:
                self._send_mouse_raw(btn_up_map[b])


# ── Servidor RemoteLink ───────────────────────────────────────────────────────

class RemoteLinkServer:

    def __init__(self,
                 port: int = FRAME_PORT,
                 access_code: str = None,
                 on_client_connect:    Callable = None,
                 on_client_disconnect: Callable = None,
                 on_status_change:     Callable = None,
                 on_network_event:     Callable = None):
        self.frame_port    = port
        self.input_port    = port + 1
        self.access_code   = (access_code or "").strip().upper()
        self.on_client_connect    = on_client_connect
        self.on_client_disconnect = on_client_disconnect
        self.on_status_change     = on_status_change
        self.on_network_event     = on_network_event

        self._frame_sock: Optional[socket.socket] = None
        self._input_sock: Optional[socket.socket] = None
        self._listener_socks: list[socket.socket] = []
        self.listening_ports: list[int] = []
        self._running     = False
        self._session_id  = None          # identifica sessão ativa
        self._frame_conn: Optional[socket.socket] = None
        self._relay_sock  = None

        # Geometria real do monitor capturado (para mapeamento exato do mouse)
        self._mon_rect = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self._win_injector = Win32InputInjector() if _IS_WIN else None
        self._last_client_ack = 0.0
        self.upnp_status = {"ok": False, "external_ip": None}
        self.relay_active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._bind_all_open_ports()
        threading.Thread(target=self._listen_input,
                         daemon=True, name="RL-InputListen").start()
        threading.Thread(target=self._external_network_loop,
                         daemon=True, name="RL-ExtNet").start()
        threading.Thread(target=self._relay_listen_loop,
                         daemon=True, name="RL-RelayListen").start()
        self._notify_status("listening")
        logger.info(f"RemoteLink: portas ativas {self.listening_ports} | input:{self.input_port}")

    def _bind_all_open_ports(self):
        """
        Escuta simultaneamente na porta principal (52340) e nas portas abertas/comuns
        do computador (7070, 6568, 8080, 8443, 33890, 443, 80) estilo AnyDesk.
        Cada porta aceita conexões multiplexadas (frames + input no mesmo socket).
        """
        from core.identity import CANDIDATE_OPEN_PORTS
        candidates = [self.frame_port]
        for p in CANDIDATE_OPEN_PORTS:
            if p not in candidates and p != self.input_port:
                candidates.append(p)

        self.listening_ports = []
        self._listener_socks = []
        for p in candidates:
            try:
                s = self._make_server_sock(p)
                if self._frame_sock is None:
                    self._frame_sock = s
                self._listener_socks.append(s)
                self.listening_ports.append(p)
                threading.Thread(
                    target=self._accept_loop_on_sock,
                    args=(s, p),
                    daemon=True,
                    name=f"RL-Listen-{p}",
                ).start()
            except Exception as e:
                logger.debug(f"Porta {p} indisponível para escuta: {e}")

    def _accept_loop_on_sock(self, srv_sock: socket.socket, port: int):
        while self._running:
            try:
                conn, addr = srv_sock.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                threading.Thread(
                    target=self._handle_frame_conn,
                    args=(conn, addr),
                    daemon=True,
                    name=f"RL-Frame-{port}-{addr[0]}",
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        self._running = False
        if self._win_injector:
            try:
                self._win_injector.release_all()
            except Exception:
                pass
        for s in list(self._listener_socks) + [self._frame_sock, self._input_sock, self._frame_conn]:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        if self._relay_sock:
            try:
                self._relay_sock.close()
            except Exception:
                pass
        self._notify_status("stopped")

    def _notify_net(self, msg: str):
        logger.info(msg)
        if self.on_network_event:
            try:
                self.on_network_event(msg)
            except Exception:
                pass

    def _external_network_loop(self):
        """
        Configura Firewall, UPnP IGD em todas as portas abertas do computador,
        descobre IP público via STUN/HTTP, publica presença no CloudRegistry
        e escuta pedidos de conexão reversa.
        """
        from core.identity import (
            ensure_firewall_rules, UPnPManager, get_public_ip,
            get_machine_info, CloudRegistry, encode_external_code
        )
        ports_to_open = tuple(self.listening_ports or [self.frame_port]) + (self.input_port,)
        try:
            ensure_firewall_rules(ports_to_open)
        except Exception:
            pass

        try:
            upnp_res = UPnPManager.forward_ports(ports_to_open[:6])
            self.upnp_status = upnp_res
            if upnp_res.get("ok"):
                self._notify_net(
                    f"UPnP ativo: portas {upnp_res.get('ports')} abertas no roteador"
                )
            else:
                self._notify_net(
                    f"Portas locais ativas: {self.listening_ports} + Relay Externo automatico ativo"
                )
        except Exception as e:
            logger.debug(f"UPnP init: {e}")

        pub_ip = self.upnp_status.get("external_ip") or get_public_ip(force_refresh=True)
        minfo = get_machine_info(fetch_public=False)
        minfo["open_ports"] = list(self.listening_ports)
        if pub_ip:
            minfo["public_ip"] = pub_ip
            ext_token = encode_external_code(self.access_code, pub_ip, self.frame_port)
            self._notify_net(f"Rede Externa pronta — IP: {pub_ip} | Portas: {self.listening_ports} | Token: {ext_token}")

        seen_signals = set()
        last_pub = 0.0

        while self._running:
            now = time.time()
            # Publica presença na nuvem a cada 60 segundos
            if now - last_pub >= 60.0:
                last_pub = now
                ok = CloudRegistry.publish_presence(
                    minfo,
                    port=self.frame_port,
                    open_ports=self.listening_ports,
                    upnp_ok=bool(self.upnp_status.get("ok")),
                )
                if ok and last_pub == now:
                    logger.debug("Presenca publicada no CloudRegistry")

            # Verifica solicitações de conexão reversa (quando Host está atrás de CGNAT)
            if not self._frame_conn:
                reqs = CloudRegistry.poll_reverse_requests(self.access_code, seen_signals)
                for req in reqs:
                    threading.Thread(
                        target=self._handle_reverse_connect,
                        args=(req,),
                        daemon=True,
                        name="RL-RevOut"
                    ).start()

            for _ in range(15):
                if not self._running:
                    return
                time.sleep(0.2)

    def _relay_listen_loop(self):
        """
        Mantém canal TCP de saída permanente com o Relay Externo (MQTT v3.1.1 over TCP).
        Permite que qualquer máquina fora da rede conecte mesmo quando todas as portas
        de entrada estão bloqueadas por CGNAT/Firewall da operadora!
        """
        from core.identity import MQTTRelaySocket, CloudRegistry

        ctrl_fallback = None
        if not _IS_WIN:
            try:
                from pynput.mouse import Controller as MouseCtrl
                from pynput.keyboard import Controller as KeyCtrl
                ctrl_fallback = (MouseCtrl(), KeyCtrl())
            except Exception:
                pass

        while self._running:
            if not self.access_code:
                time.sleep(1.0)
                continue

            topics = CloudRegistry.relay_topics_for_code(self.access_code)

            def _on_relay_msg(topic: str, payload: bytes):
                try:
                    if topic == topics["input"]:
                        self._last_client_ack = time.perf_counter()
                        if len(payload) > 5 and payload[0] == 0x02:
                            ev = json.loads(payload[5:].decode("utf-8", errors="ignore"))
                        else:
                            ev = json.loads(payload.decode("utf-8", errors="ignore"))
                        self._exec_input(ev, ctrl_fallback)
                    elif topic == topics["ctrl"]:
                        msg = json.loads(payload.decode("utf-8", errors="ignore"))
                        cmd = msg.get("cmd")
                        if cmd == "connect":
                            c_code = normalize_code(msg.get("access_code", ""))
                            o_code = normalize_code(self.access_code)
                            sid = msg.get("session_id") or str(uuid.uuid4())[:8]
                            if c_code and o_code and c_code != o_code:
                                if self._relay_sock:
                                    self._relay_sock.publish(topics["handshake"], json.dumps({
                                        "status": "rejected",
                                        "session_id": sid,
                                        "reason": "Código de acesso inválido",
                                    }).encode("utf-8"))
                                return

                            self._session_id = sid
                            self._last_client_ack = time.perf_counter()
                            if self._relay_sock:
                                self._relay_sock.publish(topics["handshake"], json.dumps({
                                    "status":     "accepted",
                                    "session_id": sid,
                                    "machine":    self._host_info(),
                                    "version":    PROTO_VER,
                                    "mode":       "relay",
                                }).encode("utf-8"))
                            self._notify_status("connected")
                            if self.on_client_connect:
                                self.on_client_connect(("Relay Externo", 443), self._host_info())
                            threading.Thread(
                                target=self._relay_capture_loop,
                                args=(self._relay_sock, topics["frame"], sid),
                                daemon=True,
                                name=f"RL-RelayCap-{sid}",
                            ).start()
                        elif cmd == "ack":
                            self._last_client_ack = time.perf_counter()
                        elif cmd == "disconnect":
                            if self._session_id == msg.get("session_id"):
                                self._session_id = None
                                if self._win_injector:
                                    try:
                                        self._win_injector.release_all()
                                    except Exception:
                                        pass
                                self._notify_status("listening")
                                if self.on_client_disconnect:
                                    self.on_client_disconnect()
                except Exception as e:
                    logger.debug(f"relay_msg err: {e}")

            relay = MQTTRelaySocket(on_message=_on_relay_msg)
            if relay.connect(timeout=5.0):
                self._relay_sock = relay
                self.relay_active = True
                relay.subscribe(topics["ctrl"])
                relay.subscribe(topics["input"])
                logger.info(f"Relay Externo conectado para código {self.access_code}")
                while self._running and relay.connected:
                    time.sleep(1.0)
                self.relay_active = False
            else:
                self.relay_active = False
                for _ in range(15):
                    if not self._running:
                        return
                    time.sleep(0.3)

    def _grab_screen_image(self, sct, mon):
        from PIL import Image
        if sct is not None and mon is not None:
            try:
                raw = sct.grab(mon)
                return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            except Exception:
                pass
        try:
            from PIL import ImageGrab
            return ImageGrab.grab().convert("RGB")
        except Exception:
            pass
        from PIL import ImageDraw
        w = max(640, min(1280, int(self._mon_rect.get("width", 1280))))
        h = max(360, min(720, int(self._mon_rect.get("height", 720))))
        img = Image.new("RGB", (w, h), (13, 19, 31))
        d = ImageDraw.Draw(img)
        d.text((48, 48), f"RemoteLink Host Ativo — {socket.gethostname()}", fill=(96, 165, 250))
        d.text((48, 82), f"Horário: {time.strftime('%H:%M:%S')}  |  Controle Direto de Teclado & Mouse Ativo", fill=(148, 163, 184))
        return img

    def _relay_capture_loop(self, relay, frame_topic: str, sid: str):
        """Envia frames da tela pelo túnel Relay Externo quando as portas diretas estão sob CGNAT."""
        try:
            from PIL import Image
        except ImportError:
            return

        sct = None
        mon = None
        try:
            import mss
            sct = mss.mss()
            mon = sct.monitors[1]
            self._mon_rect = {
                "left":   int(mon.get("left", 0)),
                "top":    int(mon.get("top", 0)),
                "width":  int(mon.get("width", 1920)),
                "height": int(mon.get("height", 1080)),
            }
        except Exception:
            pass

        buf = io.BytesIO()
        quality = 50
        max_w   = 1152
        target_dt = 1.0 / 12.0

        while self._running and self._session_id == sid and relay and relay.connected:
            t0 = time.perf_counter()
            if t0 - self._last_client_ack > 300.0:
                break
            try:
                img = self._grab_screen_image(sct, mon)
                w, h = img.size
                if w > max_w:
                    scale = max_w / w
                    img = img.resize((max_w, int(h * scale)), Image.BILINEAR)

                buf.seek(0)
                buf.truncate(0)
                img.save(buf, "JPEG", quality=quality, subsampling=2, optimize=False)
                frame = buf.getvalue()
                ts = int(time.time() * 1000) & 0xFFFFFFFF
                hdr = struct.pack(">BII", 0x01, len(frame), ts)
                if not relay.publish(frame_topic, hdr + frame):
                    break
            except Exception:
                time.sleep(0.05)

            dt = time.perf_counter() - t0
            if dt < target_dt:
                time.sleep(target_dt - dt)

        try:
            if sct:
                sct.close()
        except Exception:
            pass
        if self._session_id == sid:
            self._session_id = None
            if self._running:
                self._notify_status("listening")
                if self.on_client_disconnect:
                    self.on_client_disconnect()

    def _handle_reverse_connect(self, req: dict):
        """Conecta ativamente do Host para o Viewer quando solicitado via CloudRegistry."""
        endpoints = req.get("endpoints") or []
        port = int(req.get("port") or 52345)
        for ip in endpoints:
            if not self._running or self._frame_conn:
                return
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.settimeout(4.0)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.connect((ip, port))
                self._notify_net(f"Conexao reversa estabelecida com Viewer {ip}:{port}")
                self._handle_frame_conn(conn, (ip, port), reverse_viewer_addr=(ip, port))
                return
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    def _make_server_sock(self, port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        s.settimeout(1.0)
        return s

    # ── Canal de frames + Multiplexação em Porta Única ────────────────────

    def _handle_frame_conn(self, conn: socket.socket, addr,
                           reverse_viewer_addr: Optional[tuple] = None):
        """Handshake no canal de frames → autenticação → stream + input multiplexado."""
        try:
            conn.settimeout(10.0)
            raw = self._recv_msg(conn)
            if not raw:
                conn.close()
                return

            hello       = json.loads(raw)
            is_probe    = hello.get("probe", False)
            client_code = normalize_code(hello.get("access_code", ""))
            own_code    = normalize_code(self.access_code)

            # Probe mode
            if is_probe:
                self._send_msg(conn, json.dumps({
                    "status":  "info",
                    "machine": self._host_info(),
                    "version": PROTO_VER,
                }).encode())
                conn.close()
                return

            # Validação de código (normalizado apenas dígitos)
            if client_code and own_code:
                if client_code != own_code:
                    self._send_msg(conn, json.dumps({
                        "status": "rejected",
                        "reason": "Código de acesso inválido",
                    }).encode())
                    conn.close()
                    logger.warning(f"Código inválido de {addr}")
                    return

            # Aceita — guarda session_id para parear com canal de input
            sid = str(uuid.uuid4())[:8]
            self._session_id = sid
            self._last_client_ack = time.perf_counter()

            self._send_msg(conn, json.dumps({
                "status":        "accepted",
                "machine":       self._host_info(),
                "version":       PROTO_VER,
                "session_id":    sid,
                "input_port":    self.input_port,
                "single_socket": True,
                "open_ports":    self.listening_ports,
            }).encode())

            # Se for conexão reversa, tenta abrir segundo socket opcional, mas o canal único já cobre input!
            if reverse_viewer_addr:
                try:
                    iconn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    iconn.settimeout(3.0)
                    iconn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    iconn.connect(reverse_viewer_addr)
                    threading.Thread(
                        target=self._handle_input_conn,
                        args=(iconn, reverse_viewer_addr),
                        daemon=True,
                        name=f"RL-RevInput-{reverse_viewer_addr[0]}"
                    ).start()
                except Exception as e:
                    logger.debug(f"Reverse input secondary socket skipped (using mux): {e}")

            self._frame_conn = conn
            conn.settimeout(None)

            # Inicia leitor de input multiplexado no próprio socket de frames (1 única porta aberta!)
            ctrl_fallback = None
            if not _IS_WIN:
                try:
                    from pynput.mouse import Controller as MouseCtrl
                    from pynput.keyboard import Controller as KeyCtrl
                    ctrl_fallback = (MouseCtrl(), KeyCtrl())
                except Exception:
                    pass
            threading.Thread(
                target=self._input_loop,
                args=(conn, ctrl_fallback),
                daemon=True,
                name=f"RL-MuxInput-{sid}",
            ).start()

            self._notify_status("connected")
            if self.on_client_connect:
                self.on_client_connect(addr, self._host_info())

            # Inicia stream de frames nesta thread
            self._capture_loop(conn, sid, addr[0])

        except Exception as e:
            logger.error(f"frame_conn error: {e}")
        finally:
            if self._win_injector:
                try:
                    self._win_injector.release_all()
                except Exception:
                    pass
            conn.close()
            if self._frame_conn is conn:
                self._frame_conn = None
            if locals().get("sid") and self._session_id == locals().get("sid"):
                self._session_id = None
            if self._running and not self._session_id:
                self._notify_status("listening")
                if self.on_client_disconnect:
                    self.on_client_disconnect()

    # ── Canal de input (52341) ────────────────────────────────────────────

    def _listen_input(self):
        try:
            self._input_sock = self._make_server_sock(self.input_port)
            while self._running:
                try:
                    conn, addr = self._input_sock.accept()
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    threading.Thread(target=self._handle_input_conn,
                                     args=(conn, addr),
                                     daemon=True, name=f"RL-Input-{addr[0]}").start()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception as e:
            logger.error(f"Input listen error: {e}")

    def _handle_input_conn(self, conn: socket.socket, addr):
        """Recebe eventos de input do cliente."""
        try:
            conn.settimeout(10.0)
            raw = self._recv_msg(conn)
            if not raw:
                conn.close()
                return

            hello      = json.loads(raw)
            session_id = hello.get("session_id", "")

            if session_id != self._session_id:
                self._send_msg(conn, json.dumps({"status": "rejected"}).encode())
                conn.close()
                logger.warning(f"Input session inválida de {addr}: {session_id!r}")
                return

            self._send_msg(conn, json.dumps({"status": "ok"}).encode())
            conn.settimeout(None)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            logger.info(f"Canal de input conectado: {addr}")

            # Fallback pynput apenas se não estiver no Windows
            ctrl = None
            if not _IS_WIN:
                try:
                    from pynput.mouse import Controller as MouseCtrl
                    from pynput.keyboard import Controller as KeyCtrl
                    ctrl = (MouseCtrl(), KeyCtrl())
                except ImportError:
                    logger.error("pynput not found! pip install pynput")

            self._input_loop(conn, ctrl)

        except Exception as e:
            logger.error(f"input_conn error: {e}")
        finally:
            if self._win_injector:
                try:
                    self._win_injector.release_all()
                except Exception:
                    pass
            conn.close()

    def _input_loop(self, conn: socket.socket, ctrl):
        """Loop de recepção de eventos de input."""
        while self._running:
            try:
                hdr = self._recv_exact(conn, 5)
                if not hdr:
                    break
                msg_type, msg_len = struct.unpack(">BI", hdr)
                if msg_len == 0:
                    continue
                if msg_len > 65536:
                    break
                data = self._recv_exact(conn, msg_len)
                if not data:
                    break

                if msg_type == 0x02:   # input event
                    self._exec_input(json.loads(data), ctrl)
                elif msg_type == 0x03: # control
                    ctrl_msg = json.loads(data)
                    cmd = ctrl_msg.get("cmd")
                    if cmd == "ack":
                        self._last_client_ack = time.perf_counter()
                    elif cmd == "disconnect":
                        if self._frame_conn:
                            try:
                                self._frame_conn.close()
                            except Exception:
                                pass
                        break
            except Exception as e:
                logger.debug(f"input_loop: {e}")
                break

    # ── Execução de input (Win32 SendInput Nativo + Fallback Multiplataforma) ──

    def _resolve_screen_coords(self, ev: dict) -> tuple[int, int]:
        """Converte coordenadas normalizadas (nx, ny) ou pixels em coordenadas reais do monitor."""
        m = self._mon_rect
        nx = ev.get("nx")
        ny = ev.get("ny")
        if nx is not None and ny is not None:
            rx = m["left"] + int(max(0.0, min(1.0, float(nx))) * max(1, m["width"] - 1))
            ry = m["top"]  + int(max(0.0, min(1.0, float(ny))) * max(1, m["height"] - 1))
            return rx, ry
        return m["left"] + int(ev.get("x", 0)), m["top"] + int(ev.get("y", 0))

    def _exec_input(self, ev: dict, ctrl):
        t = ev.get("type")

        # Caminho rápido nativo Windows via SendInput (igual ao AnyDesk.exe)
        if _IS_WIN and self._win_injector is not None:
            try:
                if t == "mouse_move":
                    rx, ry = self._resolve_screen_coords(ev)
                    self._win_injector.mouse_move(rx, ry)
                elif t == "mouse_click":
                    rx, ry = self._resolve_screen_coords(ev)
                    self._win_injector.mouse_click(
                        rx, ry,
                        ev.get("button", "left"),
                        ev.get("state", "down"),
                    )
                elif t == "mouse_scroll":
                    rx, ry = self._resolve_screen_coords(ev)
                    self._win_injector.mouse_scroll(
                        rx, ry,
                        int(ev.get("delta", 0)),
                        int(ev.get("dx", 0)),
                    )
                elif t == "key_down":
                    self._win_injector.key_event(
                        is_up=False,
                        key=ev.get("key", ""),
                        vk=int(ev.get("vk", 0)),
                        scan=int(ev.get("scan", 0)),
                        char=ev.get("char", ""),
                        extended=bool(ev.get("ext", False)),
                    )
                elif t == "key_up":
                    self._win_injector.key_event(
                        is_up=True,
                        key=ev.get("key", ""),
                        vk=int(ev.get("vk", 0)),
                        scan=int(ev.get("scan", 0)),
                        extended=bool(ev.get("ext", False)),
                    )
                elif t == "type_text":
                    txt = ev.get("text", "")
                    if txt:
                        self._win_injector.type_text(txt)
                elif t == "release_all":
                    self._win_injector.release_all()
            except Exception as e:
                logger.warning(f"Win32 exec_input [{t}]: {e}")
            return

        # Fallback Linux / macOS via pynput
        if not ctrl:
            return

        m_ctrl, k_ctrl = ctrl
        try:
            rx, ry = self._resolve_screen_coords(ev)
            if t == "mouse_move":
                m_ctrl.position = (rx, ry)
            elif t == "mouse_click":
                btn = ev.get("button", "left")
                from pynput.mouse import Button
                pbtn = getattr(Button, btn, Button.left)
                m_ctrl.position = (rx, ry)
                if ev.get("state") == "down":
                    m_ctrl.press(pbtn)
                else:
                    m_ctrl.release(pbtn)
            elif t == "mouse_scroll":
                m_ctrl.scroll(int(ev.get("dx", 0)), int(ev.get("delta", 0)))
            elif t in ("key_down", "key_up"):
                key = ev.get("key", "")
                if key:
                    from pynput.keyboard import Key
                    alias = {
                        "win": "cmd", "lwin": "cmd", "rwin": "cmd_r",
                        "prtscr": "print_screen", "printscreen": "print_screen",
                        "pageup": "page_up", "pagedown": "page_down",
                        "capslock": "caps_lock", "numlock": "num_lock",
                        "scrolllock": "scroll_lock", "escape": "esc",
                    }.get(key.lower(), key.lower())
                    k = getattr(Key, alias, key if len(key) == 1 else None)
                    if k:
                        if t == "key_down":
                            k_ctrl.press(k)
                        else:
                            k_ctrl.release(k)
            elif t == "type_text":
                text = ev.get("text", "")
                if text:
                    k_ctrl.type(text)
        except Exception as e:
            logger.warning(f"exec_input [{t}]: {e}")

    # ── Captura de tela (Adaptativa LAN / Rede Externa WAN) ───────────────

    def _capture_loop(self, conn: socket.socket, sid: str, client_ip: str = ""):
        try:
            from PIL import Image
        except ImportError:
            logger.error("pip install Pillow")
            self._placeholder_loop(conn, sid)
            return

        sct = None
        mon = None
        try:
            import mss
            sct = mss.mss()
            mon = sct.monitors[1]
            self._mon_rect = {
                "left":   int(mon.get("left", 0)),
                "top":    int(mon.get("top", 0)),
                "width":  int(mon.get("width", 1920)),
                "height": int(mon.get("height", 1080)),
            }
        except Exception as e:
            logger.info(f"mss init fallback ({e})")

        logger.info(f"Capturando monitor: {self._mon_rect}")
        err_ts = 0

        is_wan = not client_ip.startswith(("192.168.", "10.", "172.", "127."))
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024 if is_wan else 512 * 1024)
        except Exception:
            pass

        buf = io.BytesIO()
        quality = 62 if is_wan else 72
        max_w   = 1600 if is_wan else 1920

        while self._running and self._session_id == sid:
            t0 = time.perf_counter()
            try:
                img = self._grab_screen_image(sct, mon)
                w, h = img.size

                if w > max_w:
                    scale = max_w / w
                    img = img.resize((max_w, int(h * scale)), Image.BILINEAR)

                buf.seek(0)
                buf.truncate(0)
                subsampling = 2 if (is_wan and quality < 60) else 0
                img.save(buf, "JPEG", quality=quality, subsampling=subsampling, optimize=False)
                frame = buf.getvalue()

                ts  = int(time.time() * 1000) & 0xFFFFFFFF
                hdr = struct.pack(">BII", 0x01, len(frame), ts)
                send_t0 = time.perf_counter()
                conn.sendall(hdr + frame)
                send_dt = time.perf_counter() - send_t0

                if send_dt > 0.045:
                    quality = max(45, quality - 4)
                    max_w   = 1366
                elif send_dt < 0.012 and quality < (68 if is_wan else 75):
                    quality += 1

            except (BrokenPipeError, ConnectionResetError, OSError):
                break
            except Exception as e:
                now = time.time()
                if now - err_ts > 2.0:
                    logger.warning(f"capture: {e}")
                    err_ts = now
                time.sleep(0.05)
                continue

            elapsed = time.perf_counter() - t0
            wait = FRAME_TIME - elapsed
            if wait > 0:
                time.sleep(wait)

        try:
            if sct:
                sct.close()
        except Exception:
            pass

    def _placeholder_loop(self, conn, sid):
        from PIL import Image, ImageDraw
        while self._running and self._session_id == sid:
            img = Image.new("RGB", (960, 540), (18, 20, 28))
            d = ImageDraw.Draw(img)
            d.text((340, 250), "Instale: pip install mss", fill=(120, 120, 140))
            d.text((400, 290), time.strftime("%H:%M:%S"), fill=(80, 120, 200))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
            frame = buf.getvalue()
            hdr = struct.pack(">BII", 0x01, len(frame), 0)
            try:
                conn.sendall(hdr + frame)
            except Exception:
                break
            time.sleep(1 / 10)

    # ── Info / Wire ───────────────────────────────────────────────────────

    def _host_info(self):
        from core.identity import get_local_ip, get_all_local_ips, get_public_ip
        return {
            "hostname":         socket.gethostname(),
            "access_code":      self.access_code,
            "platform":         platform.system(),
            "platform_version": platform.version()[:40],
            "machine":          platform.machine(),
            "local_ip":         get_local_ip(),
            "public_ip":        get_public_ip(),
            "all_ips":          get_all_local_ips(),
            "open_ports":       list(self.listening_ports),
            "screen_width":     self._mon_rect["width"],
            "screen_height":    self._mon_rect["height"],
        }

    def _send_msg(self, conn, data: bytes):
        conn.sendall(struct.pack(">I", len(data)) + data)

    def _recv_msg(self, conn) -> Optional[bytes]:
        hdr = self._recv_exact(conn, 4)
        if not hdr:
            return None
        n = struct.unpack(">I", hdr)[0]
        if n > 10 * 1024 * 1024:
            return None
        return self._recv_exact(conn, n)

    def _recv_exact(self, conn, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            try:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except Exception:
                return None
        return buf

    def _notify_status(self, s: str):
        if self.on_status_change:
            try:
                self.on_status_change(s)
            except Exception:
                pass
