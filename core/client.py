"""
RemoteLink - Client (Viewer) Module
Connects to a remote machine, receives screen, sends input events.
"""

import socket
import threading
import struct
import json
import time
import logging
from typing import Callable, Optional

logger = logging.getLogger("remotelink.client")

REMOTELINK_PORT = 52340
PROTOCOL_VERSION = 1
CONNECTION_TIMEOUT = 10.0


class RemoteLinkClient:
    """
    Client that connects to a remote RemoteLink server.
    Receives screen frames and sends input events.
    """

    def __init__(
        self,
        on_frame: Callable = None,
        on_connected: Callable = None,
        on_disconnected: Callable = None,
        on_status_change: Callable = None,
        on_error: Callable = None,
    ):
        self.on_frame = on_frame
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_status_change = on_status_change
        self.on_error = on_error

        self._sock: Optional[socket.socket] = None
        self._running = False
        self._connected = False
        self._recv_thread: Optional[threading.Thread] = None

        self.remote_info: Optional[dict] = None

    def connect(self, ip: str, port: int = REMOTELINK_PORT,
                access_code: str = "", local_access_code: str = "") -> bool:
        """
        Connect to a remote machine.
        Returns True if handshake succeeded, False otherwise.
        """
        self._notify_status("connecting")
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECTION_TIMEOUT)
            sock.connect((ip, port))

            # Send hello
            hello = json.dumps({
                "version": PROTOCOL_VERSION,
                "access_code": access_code,
                "viewer_code": local_access_code,
            }).encode()
            self._send_message(sock, hello)

            # Receive response
            response_raw = self._recv_message(sock)
            if not response_raw:
                sock.close()
                self._notify_error("No response from server")
                return False

            response = json.loads(response_raw)

            if response.get("status") != "accepted":
                reason = response.get("reason", "Connection rejected")
                sock.close()
                self._notify_error(reason)
                return False

            # Store remote info
            self.remote_info = response.get("machine", {})
            self._sock = sock
            self._running = True
            self._connected = True
            sock.settimeout(None)

            # Start receiving frames
            self._recv_thread = threading.Thread(
                target=self._recv_loop, daemon=True
            )
            self._recv_thread.start()

            self._notify_status("connected")
            if self.on_connected:
                self.on_connected(self.remote_info)

            return True

        except socket.timeout:
            self._notify_error("Connection timed out")
            return False
        except ConnectionRefusedError:
            self._notify_error("Connection refused - is RemoteLink running on the target?")
            return False
        except Exception as e:
            self._notify_error(str(e))
            return False

    def disconnect(self):
        """Disconnect from the remote machine."""
        self._running = False
        self._connected = False

        if self._sock:
            try:
                # Send disconnect command
                self._send_control({"cmd": "disconnect"})
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        self._notify_status("disconnected")
        if self.on_disconnected:
            self.on_disconnected()

    def send_mouse_move(self, x: int, y: int):
        """Send mouse move event."""
        self._send_input({"type": "mouse_move", "x": x, "y": y})

    def send_mouse_click(self, x: int, y: int, button: str = "left"):
        """Send mouse click event."""
        self._send_input({"type": "mouse_click", "x": x, "y": y, "button": button})

    def send_mouse_dblclick(self, x: int, y: int):
        """Send double click event."""
        self._send_input({"type": "mouse_dblclick", "x": x, "y": y})

    def send_mouse_scroll(self, x: int, y: int, delta: int):
        """Send scroll event."""
        self._send_input({"type": "mouse_scroll", "x": x, "y": y, "delta": delta})

    def send_key_press(self, key: str):
        """Send key press event."""
        self._send_input({"type": "key_press", "key": key})

    def send_hotkey(self, *keys):
        """Send hotkey combination."""
        self._send_input({"type": "key_hotkey", "keys": list(keys)})

    def send_text(self, text: str):
        """Send text to type."""
        self._send_input({"type": "type_text", "text": text})

    def is_connected(self) -> bool:
        return self._connected

    def _recv_loop(self):
        """Main receive loop for screen frames."""
        try:
            while self._running and self._sock:
                # Read 9-byte frame header: type(1) + length(4) + timestamp(4)
                header = self._recv_exact(self._sock, 9)
                if not header:
                    break

                msg_type, msg_len, timestamp = struct.unpack(">BII", header)

                if msg_len == 0:
                    continue

                if msg_len > 20 * 1024 * 1024:  # 20MB max
                    logger.warning(f"Frame too large: {msg_len}")
                    break

                data = self._recv_exact(self._sock, msg_len)
                if not data:
                    break

                if msg_type == 0x01:  # Screen frame (JPEG)
                    if self.on_frame:
                        self.on_frame(data, timestamp)

        except Exception as e:
            logger.debug(f"Recv loop ended: {e}")
        finally:
            self._connected = False
            if self._running:
                self._running = False
                self._notify_status("disconnected")
                if self.on_disconnected:
                    self.on_disconnected()

    def _send_input(self, event: dict):
        """Send an input event to the server."""
        if not self._connected or not self._sock:
            return
        try:
            data = json.dumps(event).encode()
            header = struct.pack(">BI", 0x02, len(data))
            self._sock.sendall(header + data)
        except Exception as e:
            logger.debug(f"Send input error: {e}")
            self.disconnect()

    def _send_control(self, msg: dict):
        """Send a control message."""
        if not self._sock:
            return
        try:
            data = json.dumps(msg).encode()
            header = struct.pack(">BI", 0x03, len(data))
            self._sock.sendall(header + data)
        except Exception:
            pass

    def _send_message(self, sock: socket.socket, data: bytes):
        header = struct.pack(">I", len(data))
        sock.sendall(header + data)

    def _recv_message(self, sock: socket.socket) -> Optional[bytes]:
        header = self._recv_exact(sock, 4)
        if not header:
            return None
        length = struct.unpack(">I", header)[0]
        if length > 10 * 1024 * 1024:
            return None
        return self._recv_exact(sock, length)

    def _recv_exact(self, sock: socket.socket, n: int) -> Optional[bytes]:
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception:
                return None
        return data

    def _notify_status(self, status: str):
        if self.on_status_change:
            self.on_status_change(status)

    def _notify_error(self, message: str):
        logger.error(f"Client error: {message}")
        if self.on_error:
            self.on_error(message)


def probe_target(ip: str, port: int = REMOTELINK_PORT, timeout: float = 3.0) -> dict:
    """
    Probe a target to get its machine info before connecting.
    Returns info dict or raises exception.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))

        # Send probe hello (no access code)
        hello = json.dumps({
            "version": PROTOCOL_VERSION,
            "access_code": "__probe__",
            "probe": True,
        }).encode()

        header = struct.pack(">I", len(hello))
        sock.sendall(header + hello)

        # Receive
        resp_header = b""
        while len(resp_header) < 4:
            chunk = sock.recv(4 - len(resp_header))
            if not chunk:
                break
            resp_header += chunk

        if len(resp_header) == 4:
            length = struct.unpack(">I", resp_header)[0]
            if 0 < length < 10 * 1024:
                resp_data = b""
                while len(resp_data) < length:
                    chunk = sock.recv(length - len(resp_data))
                    if not chunk:
                        break
                    resp_data += chunk
                
                if resp_data:
                    response = json.loads(resp_data)
                    machine = response.get("machine", {})
                    machine["reachable"] = True
                    machine["ip"] = ip
                    sock.close()
                    return machine

        sock.close()
        return {"reachable": True, "ip": ip, "hostname": ip}

    except socket.timeout:
        return {"reachable": False, "ip": ip, "error": "timeout"}
    except ConnectionRefusedError:
        return {"reachable": False, "ip": ip, "error": "refused"}
    except Exception as e:
        return {"reachable": False, "ip": ip, "error": str(e)}
