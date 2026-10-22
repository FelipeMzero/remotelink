"""
RemoteLink - Audio & Microphone Engine
Transmissão de som do computador (Host -> Viewer) e microfone (Viewer -> Host)
com baixíssima latência (PCM 24kHz 16-bit Mono, ~40ms por bloco).
"""

import threading
import queue
import time
import logging
from typing import Callable, Optional

logger = logging.getLogger("remotelink.audio")

SAMPLE_RATE = 24000
CHANNELS    = 1
DTYPE       = "int16"
BLOCK_SIZE  = 1024  # ~42.6 ms de áudio

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    _SD_AVAILABLE = False


class AudioCapture:
    """Captura de áudio (microfone ou som do sistema) em tempo real."""

    def __init__(self, on_chunk: Callable[[bytes], None], device_type: str = "mic"):
        self.on_chunk = on_chunk
        self.device_type = device_type
        self._stream = None
        self._running = False
        self._lock = threading.Lock()

    def _pick_device(self) -> Optional[int]:
        if not _SD_AVAILABLE:
            return None
        try:
            devs = sd.query_devices()
            if self.device_type == "speaker":
                # Tenta Mixagem estéreo / Stereo Mix para som do sistema
                for i, d in enumerate(devs):
                    name_l = d.get("name", "").lower()
                    if d.get("max_input_channels", 0) > 0 and (
                        "mixagem" in name_l or "stereo mix" in name_l or "what u hear" in name_l or "wave out" in name_l
                    ):
                        return i
            # Fallback para dispositivo padrão de entrada
            def_in = sd.default.device[0]
            if def_in is not None and def_in >= 0:
                return def_in
            for i, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0:
                    return i
        except Exception as e:
            logger.debug(f"pick_device error: {e}")
        return None

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            if not _SD_AVAILABLE:
                logger.warning("sounddevice não disponível para captura de áudio")
                return False

            dev = self._pick_device()
            try:
                def _callback(indata, frames, time_info, status):
                    if not self._running:
                        return
                    if status and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Audio capture status: {status}")
                    raw = bytes(indata)
                    if self.on_chunk:
                        try:
                            self.on_chunk(raw)
                        except Exception:
                            pass

                self._stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    device=dev,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    callback=_callback,
                )
                self._stream.start()
                self._running = True
                logger.info(f"AudioCapture iniciado ({self.device_type}, dev={dev})")
                return True
            except Exception as e:
                logger.warning(f"Falha ao iniciar AudioCapture ({self.device_type}): {e}")
                self._stream = None
                self._running = False
                return False

    def stop(self):
        with self._lock:
            self._running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            logger.info(f"AudioCapture parado ({self.device_type})")

    @property
    def is_running(self) -> bool:
        return self._running


class AudioPlayback:
    """Reprodução contínua de áudio via buffer circular/fila anti-jitter."""

    def __init__(self):
        self._stream = None
        self._running = False
        self._queue = queue.Queue(maxsize=16)
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            if not _SD_AVAILABLE:
                return False

            try:
                def _callback(outdata, frames, time_info, status):
                    bytes_needed = frames * CHANNELS * 2  # 16-bit = 2 bytes
                    collected = bytearray()
                    while len(collected) < bytes_needed:
                        try:
                            chunk = self._queue.get_nowait()
                            collected.extend(chunk)
                        except queue.Empty:
                            break
                    if len(collected) < bytes_needed:
                        # Silêncio para completar bloco
                        collected.extend(b"\x00" * (bytes_needed - len(collected)))
                    outdata[:] = bytes(collected[:bytes_needed])

                self._stream = sd.RawOutputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    callback=_callback,
                )
                self._stream.start()
                self._running = True
                logger.info("AudioPlayback iniciado")
                return True
            except Exception as e:
                logger.warning(f"Falha ao iniciar AudioPlayback: {e}")
                self._stream = None
                self._running = False
                return False

    def write(self, data: bytes):
        if not self._running or not data:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(data)
            except Exception:
                pass

    def stop(self):
        with self._lock:
            self._running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except Exception:
                    break
            logger.info("AudioPlayback parado")

    @property
    def is_running(self) -> bool:
        return self._running


def is_audio_supported() -> bool:
    return _SD_AVAILABLE
