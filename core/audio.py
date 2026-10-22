"""
RemoteLink - High-Fidelity Low-Latency Audio Engine
Transmissão de som do sistema (Host -> Viewer via WASAPI Loopback)
e microfone (Viewer -> Host) com baixíssima latência (PCM 24kHz 16-bit Mono, ~42ms por bloco).
"""

import threading
import queue
import time
import array
import logging
from typing import Callable, Optional

logger = logging.getLogger("remotelink.audio")

SAMPLE_RATE = 24000
CHANNELS    = 1
DTYPE       = "int16"
BLOCK_SIZE  = 1024  # 1024 amostras = ~42.6 ms

_PA_AVAILABLE = False
try:
    import pyaudiowpatch as pyaudio
    _PA_AVAILABLE = True
except Exception:
    pass

_SD_AVAILABLE = False
try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    pass


class AudioCapture:
    """Captura de som do PC (WASAPI Loopback) ou Microfone em tempo real."""

    def __init__(self, on_chunk: Callable[[bytes], None], device_type: str = "speaker"):
        self.on_chunk = on_chunk
        self.device_type = device_type
        self._running = False
        self._thread = None
        self._pa_instance = None
        self._stream = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._thread = threading.Thread(target=self._capture_worker, daemon=True, name="RL-AudioCap")
            self._thread.start()
            return True

    def _capture_worker(self):
        """Worker que gerencia a captura usando PyAudioWPatch (WASAPI) ou sounddevice."""
        if _PA_AVAILABLE:
            try:
                self._run_pyaudio()
                return
            except Exception as e:
                logger.warning(f"PyAudioWPatch capture error ({self.device_type}): {e}")

        if _SD_AVAILABLE:
            try:
                self._run_sounddevice()
                return
            except Exception as e:
                logger.warning(f"sounddevice capture error ({self.device_type}): {e}")

        logger.warning(f"Nenhum backend de áudio disponível para {self.device_type}")
        self._running = False

    def _run_pyaudio(self):
        p = pyaudio.PyAudio()
        self._pa_instance = p
        stream = None
        try:
            if self.device_type == "speaker":
                # Busca dispositivo de saída padrão do WASAPI
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                def_output_idx = wasapi_info.get("defaultOutputDevice")
                default_speakers = p.get_device_info_by_index(def_output_idx)
                speaker_name = default_speakers.get("name", "")

                # Encontra o correspondente [Loopback]
                loopback = None
                for d in p.get_loopback_device_info_generator():
                    if speaker_name in d.get("name", ""):
                        loopback = d
                        break
                if not loopback:
                    try:
                        loopback = next(p.get_loopback_device_info_generator())
                    except StopIteration:
                        loopback = None

                if not loopback:
                    logger.warning("Nenhum dispositivo WASAPI Loopback encontrado.")
                    return

                dev_idx = loopback["index"]
                in_rate = int(loopback["defaultSampleRate"])
                in_channels = int(loopback["maxInputChannels"])
                frames_per_buffer = 1024
                logger.info(f"Gravando áudio do PC via Loopback: {loopback['name']} ({in_rate}Hz, {in_channels}ch)")

            else:
                # Microfone
                dev_idx = None
                in_rate = SAMPLE_RATE
                in_channels = CHANNELS
                frames_per_buffer = BLOCK_SIZE
                logger.info("Gravando áudio do Microfone padrão")

            stream = p.open(
                format=pyaudio.paInt16,
                channels=in_channels,
                rate=in_rate,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=frames_per_buffer
            )
            self._stream = stream

            step = max(1, int((in_rate / SAMPLE_RATE) * in_channels))

            while self._running:
                try:
                    data = stream.read(frames_per_buffer, exception_on_overflow=False)
                    if not data or not self._running:
                        break
                    # Conversão rápida em C para 24000Hz 16-bit Mono
                    if step > 1:
                        a = array.array("h", data)
                        mono_data = a[0::step].tobytes()
                    else:
                        mono_data = data

                    if self.on_chunk and self._running:
                        self.on_chunk(mono_data)
                except Exception as e:
                    if self._running:
                        time.sleep(0.01)
                    else:
                        break

        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            try:
                p.terminate()
            except Exception:
                pass
            self._pa_instance = None
            self._stream = None

    def _run_sounddevice(self):
        """Fallback via sounddevice se PyAudioWPatch falhar."""
        dev = None
        devs = sd.query_devices()
        if self.device_type == "speaker":
            for i, d in enumerate(devs):
                name_l = d.get("name", "").lower()
                if d.get("max_input_channels", 0) > 0 and (
                    "mixagem" in name_l or "stereo mix" in name_l or "what u hear" in name_l
                ):
                    dev = i
                    break
        if dev is None:
            dev = sd.default.device[0]

        def _callback(indata, frames, time_info, status):
            if not self._running:
                return
            raw = bytes(indata)
            if self.on_chunk:
                self.on_chunk(raw)

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            device=dev,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=_callback,
        )
        self._stream = stream
        stream.start()
        while self._running:
            time.sleep(0.1)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def stop(self):
        with self._lock:
            self._running = False
            if self._stream:
                try:
                    if hasattr(self._stream, "stop_stream"):
                        self._stream.stop_stream()
                        self._stream.close()
                    elif hasattr(self._stream, "stop"):
                        self._stream.stop()
                        self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._pa_instance:
                try:
                    self._pa_instance.terminate()
                except Exception:
                    pass
                self._pa_instance = None

    @property
    def is_running(self) -> bool:
        return self._running


class AudioPlayback:
    """Reprodução de áudio contínua (24kHz Mono 16-bit) via PyAudio ou sounddevice."""

    def __init__(self):
        self._running = False
        self._queue = queue.Queue(maxsize=32)
        self._thread = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._thread = threading.Thread(target=self._playback_worker, daemon=True, name="RL-AudioPlay")
            self._thread.start()
            return True

    def _playback_worker(self):
        if _PA_AVAILABLE:
            try:
                self._run_pyaudio()
                return
            except Exception as e:
                logger.warning(f"PyAudioWPatch playback error: {e}")

        if _SD_AVAILABLE:
            try:
                self._run_sounddevice()
                return
            except Exception as e:
                logger.warning(f"sounddevice playback error: {e}")

        self._running = False

    def _run_pyaudio(self):
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=BLOCK_SIZE
        )
        try:
            silence = b"\x00" * (BLOCK_SIZE * 2)
            while self._running:
                try:
                    chunk = self._queue.get(timeout=0.08)
                    stream.write(chunk)
                except queue.Empty:
                    # Em caso de breve buffer underrun, envia bloco de silêncio para manter o fluxo
                    stream.write(silence)
        finally:
            try:
                stream.stop_stream()
                stream.close()
                p.terminate()
            except Exception:
                pass

    def _run_sounddevice(self):
        def _callback(outdata, frames, time_info, status):
            bytes_needed = frames * CHANNELS * 2
            collected = bytearray()
            while len(collected) < bytes_needed:
                try:
                    chunk = self._queue.get_nowait()
                    collected.extend(chunk)
                except queue.Empty:
                    break
            if len(collected) < bytes_needed:
                collected.extend(b"\x00" * (bytes_needed - len(collected)))
            outdata[:] = bytes(collected[:bytes_needed])

        stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=_callback
        )
        stream.start()
        while self._running:
            time.sleep(0.1)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

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
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except Exception:
                    break

    @property
    def is_running(self) -> bool:
        return self._running


def is_audio_supported() -> bool:
    return _PA_AVAILABLE or _SD_AVAILABLE
