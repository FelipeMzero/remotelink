"""
RemoteLink - Server (Host) Module
Runs on the machine being controlled. Handles screen capture and input forwarding.
"""

import socket
import threading
import struct
import zlib
import json
import time
import platform
import logging
from typing import Callable, Optional

logger = logging.getLogger("remotelink.server")

REMOTELINK_PORT = 52340
PROTOCOL_VERSION = 1
CHUNK_SIZE = 65536


class RemoteLinkServer:
    """
    Server that runs on the host machine.
    Listens for connections and streams screen + accepts input events.
    """

    def __init__(
        self,
        port: int = REMOTELINK_PORT,
        access_code: str = None,
        on_client_connect: Callable = None,
        on_client_disconnect: Callable = None,
        on_status_change: Callable = None,
    ):
        self.port = port
        self.access_code = access_code
        self.on_client_connect = on_client_connect
        self.on_client_disconnect = on_client_disconnect
        self.on_status_change = on_status_change

        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._client_conn: Optional[socket.socket] = None
        self._client_addr = None
        self._server_thread: Optional[threading.Thread] = None
        self._capture_thread: Optional[threading.Thread] = None

    def start(self):
        """Start listening for connections."""
        self._running = True
        self._server_thread = threading.Thread(
            target=self._listen_loop, daemon=True
        )
        self._server_thread.start()
        self._notify_status("listening")
        logger.info(f"Server listening on port {self.port}")

    def stop(self):
        """Stop the server and disconnect any clients."""
        self._running = False
        if self._client_conn:
            try:
                self._client_conn.close()
            except Exception:
                pass
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self._notify_status("stopped")

    def disconnect_client(self):
        """Disconnect the current client."""
        if self._client_conn:
            try:
                self._client_conn.close()
            except Exception:
                pass
            self._client_conn = None
            self._notify_status("listening")
            if self.on_client_disconnect:
                self.on_client_disconnect()

    def _listen_loop(self):
        """Main server accept loop."""
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind(("0.0.0.0", self.port))
            self._server_sock.listen(1)
            self._server_sock.settimeout(1.0)

            while self._running:
                try:
                    conn, addr = self._server_sock.accept()
                    self._handle_client(conn, addr)
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception as e:
            logger.error(f"Server error: {e}")
            self._notify_status("error")

    def _handle_client(self, conn: socket.socket, addr):
        """Handle a new client connection."""
        logger.info(f"Client connected from {addr}")

        try:
            # Handshake
            conn.settimeout(10.0)
            
            # Receive hello
            hello_raw = self._recv_message(conn)
            if not hello_raw:
                conn.close()
                return
            
            hello = json.loads(hello_raw)
            client_version = hello.get("version", 0)
            client_code = hello.get("access_code", "")

            # Validate access code if set
            if self.access_code and client_code != self.access_code:
                self._send_message(conn, json.dumps({
                    "status": "rejected",
                    "reason": "Invalid access code"
                }).encode())
                conn.close()
                logger.warning(f"Rejected client {addr}: invalid code")
                return

            # Send welcome
            machine_info = self._get_host_info()
            self._send_message(conn, json.dumps({
                "status": "accepted",
                "machine": machine_info,
                "version": PROTOCOL_VERSION,
            }).encode())

            self._client_conn = conn
            self._client_addr = addr
            conn.settimeout(None)

            self._notify_status("connected")
            if self.on_client_connect:
                self.on_client_connect(addr, machine_info)

            # Start screen capture + input loop
            self._capture_thread = threading.Thread(
                target=self._capture_loop, args=(conn,), daemon=True
            )
            self._capture_thread.start()
            self._input_loop(conn)

        except Exception as e:
            logger.error(f"Client handling error: {e}")
        finally:
            conn.close()
            if self._client_conn == conn:
                self._client_conn = None
                self._notify_status("listening")
                if self.on_client_disconnect:
                    self.on_client_disconnect()

    def _capture_loop(self, conn: socket.socket):
        """Continuously capture and send screen frames."""
        try:
            import mss
            import mss.tools

            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                
                prev_frame = None
                fps_target = 15
                frame_time = 1.0 / fps_target

                while self._running and self._client_conn == conn:
                    start = time.time()

                    # Capture
                    img = sct.grab(monitor)
                    
                    # Convert to JPEG bytes
                    from PIL import Image
                    import io
                    pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    
                    # Scale down for performance
                    w, h = pil_img.size
                    if w > 1920:
                        scale = 1920 / w
                        pil_img = pil_img.resize(
                            (int(w * scale), int(h * scale)), Image.LANCZOS
                        )

                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=50)
                    frame_bytes = buf.getvalue()

                    # Send frame
                    header = struct.pack(">BII", 0x01, len(frame_bytes),
                                         int(time.time() * 1000) & 0xFFFFFFFF)
                    try:
                        conn.sendall(header + frame_bytes)
                    except Exception:
                        break

                    # Throttle
                    elapsed = time.time() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)

        except ImportError:
            # mss not available - send placeholder
            logger.warning("mss not available for screen capture")
            self._send_placeholder_frames(conn)
        except Exception as e:
            logger.error(f"Capture loop error: {e}")

    def _send_placeholder_frames(self, conn: socket.socket):
        """Send placeholder when screen capture not available."""
        from PIL import Image, ImageDraw
        import io

        while self._running and self._client_conn == conn:
            img = Image.new("RGB", (800, 600), color=(20, 20, 30))
            draw = ImageDraw.Draw(img)
            draw.text((300, 280), "Screen capture active", fill=(100, 200, 255))
            draw.text((310, 310), time.strftime("%H:%M:%S"), fill=(80, 160, 200))

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            frame_bytes = buf.getvalue()

            header = struct.pack(">BII", 0x01, len(frame_bytes), 0)
            try:
                conn.sendall(header + frame_bytes)
            except Exception:
                break
            time.sleep(1 / 10)

    def _input_loop(self, conn: socket.socket):
        """Receive and execute input events from client."""
        try:
            while self._running and self._client_conn == conn:
                header = self._recv_exact(conn, 5)
                if not header:
                    break
                
                msg_type, msg_len = struct.unpack(">BI", header)
                
                if msg_len > 0:
                    data = self._recv_exact(conn, msg_len)
                    if not data:
                        break
                    
                    if msg_type == 0x02:  # Input event
                        self._handle_input_event(json.loads(data))
                    elif msg_type == 0x03:  # Control message
                        ctrl = json.loads(data)
                        if ctrl.get("cmd") == "disconnect":
                            break
        except Exception as e:
            logger.debug(f"Input loop ended: {e}")

    def _handle_input_event(self, event: dict):
        """Execute mouse/keyboard input on the host machine."""
        try:
            import pyautogui
            pyautogui.FAILSAFE = False

            etype = event.get("type")

            if etype == "mouse_move":
                pyautogui.moveTo(event["x"], event["y"])
            elif etype == "mouse_click":
                btn = event.get("button", "left")
                pyautogui.click(event["x"], event["y"], button=btn)
            elif etype == "mouse_dblclick":
                pyautogui.doubleClick(event["x"], event["y"])
            elif etype == "mouse_scroll":
                pyautogui.scroll(event.get("delta", 1), x=event["x"], y=event["y"])
            elif etype == "key_press":
                pyautogui.press(event["key"])
            elif etype == "key_hotkey":
                pyautogui.hotkey(*event["keys"])
            elif etype == "type_text":
                pyautogui.typewrite(event["text"], interval=0.01)
        except ImportError:
            pass  # pyautogui not available
        except Exception as e:
            logger.debug(f"Input event error: {e}")

    def _get_host_info(self) -> dict:
        """Get info about this host machine."""
        return {
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "platform_version": platform.version()[:40],
            "machine": platform.machine(),
        }

    def _send_message(self, conn: socket.socket, data: bytes):
        """Send a length-prefixed message."""
        header = struct.pack(">I", len(data))
        conn.sendall(header + data)

    def _recv_message(self, conn: socket.socket) -> Optional[bytes]:
        """Receive a length-prefixed message."""
        header = self._recv_exact(conn, 4)
        if not header:
            return None
        length = struct.unpack(">I", header)[0]
        if length > 10 * 1024 * 1024:  # 10MB max
            return None
        return self._recv_exact(conn, length)

    def _recv_exact(self, conn: socket.socket, n: int) -> Optional[bytes]:
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            try:
                chunk = conn.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception:
                return None
        return data

    def _notify_status(self, status: str):
        if self.on_status_change:
            self.on_status_change(status)
