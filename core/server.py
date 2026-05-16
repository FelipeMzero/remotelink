"""
RemoteLink - Server (Host) Module
Dois sockets por sessão:
  - Porta 52340: canal de frames (servidor → cliente)
  - Porta 52341: canal de input  (cliente → servidor)
Elimina race condition de leitura/escrita simultânea no mesmo socket.
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
from typing import Callable, Optional

logger = logging.getLogger("remotelink.server")

FRAME_PORT  = 52340   # servidor envia frames aqui
INPUT_PORT  = 52341   # servidor recebe input aqui
PROTO_VER   = 1
FPS_TARGET  = 60
FRAME_TIME  = 1.0 / FPS_TARGET


class RemoteLinkServer:

    def __init__(self,
                 port: int = FRAME_PORT,
                 access_code: str = None,
                 on_client_connect:    Callable = None,
                 on_client_disconnect: Callable = None,
                 on_status_change:     Callable = None):
        self.frame_port    = port
        self.input_port    = port + 1
        self.access_code   = (access_code or "").strip().upper()
        self.on_client_connect    = on_client_connect
        self.on_client_disconnect = on_client_disconnect
        self.on_status_change     = on_status_change

        self._frame_sock: Optional[socket.socket] = None
        self._input_sock: Optional[socket.socket] = None
        self._running     = False
        self._session_id  = None          # identifica sessão ativa
        self._frame_conn: Optional[socket.socket] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._listen_frames,
                         daemon=True, name="RL-FrameListen").start()
        threading.Thread(target=self._listen_input,
                         daemon=True, name="RL-InputListen").start()
        self._notify_status("listening")
        logger.info(f"RemoteLink: frames:{self.frame_port} input:{self.input_port}")

    def stop(self):
        self._running = False
        for s in (self._frame_sock, self._input_sock, self._frame_conn):
            if s:
                try: s.close()
                except Exception: pass
        self._notify_status("stopped")

    def _make_server_sock(self, port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Enable TCP KeepAlive to detect dead connections faster
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        s.settimeout(1.0)
        return s

    # ── Canal de frames (52340) ───────────────────────────────────────────

    def _listen_frames(self):
        try:
            self._frame_sock = self._make_server_sock(self.frame_port)
            while self._running:
                try:
                    conn, addr = self._frame_sock.accept()
                    threading.Thread(target=self._handle_frame_conn,
                                     args=(conn, addr),
                                     daemon=True, name=f"RL-Frame-{addr[0]}").start()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception as e:
            logger.error(f"Frame listen error: {e}")

    def _handle_frame_conn(self, conn: socket.socket, addr):
        """Handshake no canal de frames → autenticação → stream."""
        try:
            conn.settimeout(10.0)
            raw = self._recv_msg(conn)
            if not raw:
                conn.close(); return

            hello       = json.loads(raw)
            is_probe    = hello.get("probe", False)
            client_code = hello.get("access_code", "").strip().upper()
            session_id  = hello.get("session_id", "")

            # Probe mode
            if is_probe:
                self._send_msg(conn, json.dumps({
                    "status":  "info",
                    "machine": self._host_info(),
                    "version": PROTO_VER,
                }).encode())
                conn.close(); return

            # Validação de código
            if client_code and self.access_code:
                if client_code != self.access_code:
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

            self._send_msg(conn, json.dumps({
                "status":     "accepted",
                "machine":    self._host_info(),
                "version":    PROTO_VER,
                "session_id": sid,
                "input_port": self.input_port,
            }).encode())

            self._frame_conn = conn
            conn.settimeout(None)

            self._notify_status("connected")
            if self.on_client_connect:
                self.on_client_connect(addr, self._host_info())

            # Inicia stream de frames nesta thread
            self._capture_loop(conn, sid)

        except Exception as e:
            logger.error(f"frame_conn error: {e}")
        finally:
            conn.close()
            if self._frame_conn is conn:
                self._frame_conn = None
                self._session_id = None
            if self._running:
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
            # Handshake de input: valida session_id
            raw = self._recv_msg(conn)
            if not raw:
                conn.close(); return

            hello      = json.loads(raw)
            session_id = hello.get("session_id", "")

            if session_id != self._session_id:
                self._send_msg(conn, json.dumps({"status": "rejected"}).encode())
                conn.close()
                logger.warning(f"Input session inválida de {addr}: {session_id!r}")
                return

            self._send_msg(conn, json.dumps({"status": "ok"}).encode())
            conn.settimeout(None)
            logger.info(f"Canal de input conectado: {addr}")

            # Input controllers
            ctrl = None
            try:
                from pynput.mouse import Controller as MouseCtrl
                from pynput.keyboard import Controller as KeyCtrl
                m_ctrl = MouseCtrl()
                k_ctrl = KeyCtrl()
                ctrl = (m_ctrl, k_ctrl)
                logger.info("pynput controllers ready")
            except ImportError:
                logger.error("pynput not found! pip install pynput")
            
            self._input_loop(conn, ctrl)

        except Exception as e:
            logger.error(f"input_conn error: {e}")
        finally:
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
                    if ctrl_msg.get("cmd") == "disconnect":
                        # Fecha canal de frames também
                        if self._frame_conn:
                            try: self._frame_conn.close()
                            except Exception: pass
                        break
            except Exception as e:
                logger.debug(f"input_loop: {e}")
                break

    # ── Execução de input ─────────────────────────────────────────────────

    def _exec_input(self, ev: dict, ctrl):
        if not ctrl:
            logger.debug(f"input ignorado (sem pynput): {ev}")
            return
        
        m_ctrl, k_ctrl = ctrl
        try:
            t = ev.get("type")
            x = int(ev.get("x", 0))
            y = int(ev.get("y", 0))
            
            if t == "mouse_move":
                m_ctrl.position = (x, y)
            elif t == "mouse_click":
                btn = ev.get("button", "left")
                # Map button names to pynput buttons
                from pynput.mouse import Button
                pbtn = getattr(Button, btn, Button.left)
                if ev.get("state") == "down":
                    m_ctrl.press(pbtn)
                else:
                    m_ctrl.release(pbtn)
            elif t == "mouse_scroll":
                m_ctrl.scroll(0, int(ev.get("delta", 0)))
            elif t == "key_down":
                key = ev.get("key", "")
                if key:
                    from pynput.keyboard import Key
                    # Try to map to special key, otherwise use character
                    k = getattr(Key, key, key)
                    k_ctrl.press(k)
            elif t == "key_up":
                key = ev.get("key", "")
                if key:
                    from pynput.keyboard import Key
                    k = getattr(Key, key, key)
                    k_ctrl.release(k)
            elif t == "type_text":
                text = ev.get("text", "")
                if text:
                    try:
                        import pyperclip
                        pyperclip.copy(text)
                        # Use hotkey for paste to be fast and handle unicode
                        from pynput.keyboard import Key
                        with k_ctrl.pressed(Key.ctrl):
                            k_ctrl.press('v')
                            k_ctrl.release('v')
                    except ImportError:
                        k_ctrl.type(text)
        except Exception as e:
            logger.warning(f"exec_input [{ev.get('type')}]: {e}")

    # ── Captura de tela ───────────────────────────────────────────────────

    def _capture_loop(self, conn: socket.socket, sid: str):
        try:
            import mss
            from PIL import Image
        except ImportError:
            logger.error("pip install mss Pillow")
            self._placeholder_loop(conn, sid); return
        
        try:
            sct = mss.mss()
        except Exception as e:
            logger.error(f"mss init: {e}")
            self._placeholder_loop(conn, sid); return
        
        mon = sct.monitors[1]
        logger.info(f"Capturando monitor: {mon}")
        err_ts = 0
        
        # Pre-allocate buffer to reduce allocations
        buf = io.BytesIO()
        
        while self._running and self._session_id == sid:
            t0 = time.perf_counter()
            try:
                raw  = sct.grab(mon)
                # Optimized conversion: BGRA -> RGB
                img  = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                w, h = img.size
                
                # Adaptive scaling: avoid overkill resolutions
                if w > 1920:
                    scale = 1920 / w
                    img = img.resize((1920, int(h * scale)), Image.BILINEAR)
                
                buf.seek(0)
                buf.truncate(0)
                # Quality 70 is often indistinguishable from 80 but much smaller
                # subsampling=0 (4:4:4) is critical for text clarity
                img.save(buf, "JPEG", quality=70, subsampling=0, optimize=False)
                frame = buf.getvalue()
                
                ts  = int(time.time()*1000) & 0xFFFFFFFF
                hdr = struct.pack(">BII", 0x01, len(frame), ts)
                conn.sendall(hdr + frame)
                
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
            except Exception as e:
                now = time.time()
                if now - err_ts > 2.0:
                    logger.warning(f"capture: {e}")
                    err_ts = now
                time.sleep(0.05); continue
            
            # Precise timing loop
            elapsed = time.perf_counter() - t0
            wait = FRAME_TIME - elapsed
            if wait > 0:
                time.sleep(wait)

        try: sct.close()
        except Exception: pass

    def _placeholder_loop(self, conn, sid):
        from PIL import Image, ImageDraw
        while self._running and self._session_id == sid:
            img = Image.new("RGB", (960,540),(18,20,28))
            d = ImageDraw.Draw(img)
            d.text((340,250),"Instale: pip install mss",fill=(120,120,140))
            d.text((400,290),time.strftime("%H:%M:%S"),fill=(80,120,200))
            buf = io.BytesIO()
            img.save(buf,"JPEG",quality=70)
            frame=buf.getvalue()
            hdr=struct.pack(">BII",0x01,len(frame),0)
            try: conn.sendall(hdr+frame)
            except Exception: break
            time.sleep(1/10)

    # ── Info / Wire ───────────────────────────────────────────────────────

    def _host_info(self):
        from core.identity import get_local_ip, get_all_local_ips
        return {
            "hostname":         socket.gethostname(),
            "platform":         platform.system(),
            "platform_version": platform.version()[:40],
            "machine":          platform.machine(),
            "local_ip":         get_local_ip(),
            "all_ips":          get_all_local_ips(),
        }

    def _send_msg(self, conn, data: bytes):
        conn.sendall(struct.pack(">I", len(data)) + data)

    def _recv_msg(self, conn) -> Optional[bytes]:
        hdr = self._recv_exact(conn, 4)
        if not hdr: return None
        n = struct.unpack(">I", hdr)[0]
        if n > 10*1024*1024: return None
        return self._recv_exact(conn, n)

    def _recv_exact(self, conn, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            try:
                chunk = conn.recv(n - len(buf))
                if not chunk: return None
                buf += chunk
            except Exception: return None
        return buf

    def _notify_status(self, s: str):
        if self.on_status_change:
            try: self.on_status_change(s)
            except Exception: pass
