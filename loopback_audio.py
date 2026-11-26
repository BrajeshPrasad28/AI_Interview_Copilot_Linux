"""
Linux audio loopback using PulseAudio / PipeWire monitor sources.

How it works on Linux:
- PulseAudio/PipeWire exposes a "monitor" source for every sink (output device).
  e.g.  "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
- We pick the default sink's monitor and record system audio without touching
  the microphone.

System dependency:
  sudo apt install portaudio19-dev python3-pyaudio   # Debian/Ubuntu
  sudo dnf install portaudio-devel python3-pyaudio   # Fedora
"""

import os
import threading
import time
import io
import wave
import logging
import subprocess
from collections import deque
from typing import Callable, Optional
import numpy as np

logger = logging.getLogger("loopback_audio")
logging.basicConfig(level=logging.INFO)


class SileroVAD:
    """
    Ultra-lightweight ONNX-powered neural Voice Activity Detection (Silero VAD).
    Runs with 0% PyTorch bloat via onnxruntime (~15MB).
    """
    def __init__(self, model_path: Optional[str] = None):
        self.session = None
        self.h = np.zeros((2, 1, 64), dtype=np.float32)
        self.c = np.zeros((2, 1, 64), dtype=np.float32)
        self.sr = np.array(16000, dtype=np.int64)

        if not model_path:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, "models", "silero_vad.onnx")

        if os.path.exists(model_path):
            try:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 1
                self.session = ort.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
                logger.info("Silero VAD ONNX neural voice detector loaded successfully.")
            except Exception as e:
                logger.warning(f"Could not load Silero VAD ONNX ({e}). Falling back to RMS volume detector.")
                self.session = None
        else:
            logger.info("Silero VAD model not found. Using RMS volume energy detection.")

    def reset_states(self):
        self.h = np.zeros((2, 1, 64), dtype=np.float32)
        self.c = np.zeros((2, 1, 64), dtype=np.float32)

    def is_speech(self, chunk_512_float32: np.ndarray, threshold: float = 0.28) -> bool:
        if self.session is None:
            return False
        try:
            if len(chunk_512_float32) != 512:
                if len(chunk_512_float32) < 512:
                    chunk_512_float32 = np.pad(chunk_512_float32, (0, 512 - len(chunk_512_float32)))
                else:
                    chunk_512_float32 = chunk_512_float32[:512]

            input_data = chunk_512_float32.reshape(1, -1)
            out, self.h, self.c = self.session.run(None, {
                'input': input_data,
                'sr': self.sr,
                'h': self.h,
                'c': self.c
            })
            prob = float(out[0][0])
            return prob >= threshold
        except Exception:
            return False


def _get_default_monitor_source() -> Optional[str]:
    """
    Query PulseAudio/PipeWire for the monitor source of the default sink.
    Returns the source name string (e.g. 'alsa_output.*.analog-stereo.monitor')
    or None if not found.
    """
    # Try pactl (PulseAudio / PipeWire-pulse)
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            sink_name = result.stdout.strip()
            if sink_name:
                monitor_name = sink_name + ".monitor"
                logger.info(f"Using PulseAudio monitor source: {monitor_name}")
                return monitor_name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: list all sources and pick first monitor
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and "monitor" in parts[1].lower():
                    logger.info(f"Using fallback monitor source: {parts[1]}")
                    return parts[1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _find_pyaudio_monitor_index(p, monitor_source_name: Optional[str]) -> Optional[int]:
    """
    Find a PyAudio monitor device or the ALSA PulseAudio endpoint.
    """
    try:
        count = p.get_device_count()
        for i in range(count):
            info = p.get_device_info_by_index(i)
            dev_name = str(info.get("name", ""))
            if info.get("maxInputChannels", 0) <= 0:
                continue
            if monitor_source_name and monitor_source_name.lower() in dev_name.lower():
                return i
            if "monitor" in dev_name.lower():
                return i

        if monitor_source_name:
            for i in range(count):
                info = p.get_device_info_by_index(i)
                if (
                    str(info.get("name", "")).strip().lower() == "pulse"
                    and info.get("maxInputChannels", 0) > 0
                    and p.get_host_api_info_by_index(info["hostApi"]).get("name", "").lower() == "alsa"
                ):
                    logger.info(
                        "Using ALSA PulseAudio endpoint for monitor source '%s'.",
                        monitor_source_name,
                    )
                    return i
    except Exception as e:
        logger.warning(f"Error scanning PyAudio devices: {e}")
    return None


def _open_pyaudio_monitor_stream(
    p,
    audio_format: int,
    device_index: int,
    monitor_source_name: str,
    channels: int,
    rate: int,
    chunk_size: int,
):
    """Open the ALSA PulseAudio endpoint with an explicit monitor source."""
    previous_source = os.environ.get("PULSE_SOURCE")
    os.environ["PULSE_SOURCE"] = monitor_source_name
    try:
        return p.open(
            format=audio_format,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=chunk_size,
        )
    finally:
        if previous_source is None:
            os.environ.pop("PULSE_SOURCE", None)
        else:
            os.environ["PULSE_SOURCE"] = previous_source


class SystemAudioLoopback:
    """
    Captures system audio from a PulseAudio/PipeWire monitor source without
    capturing microphone input.
    """

    def __init__(self, callback: Optional[Callable[[bytes], None]] = None):
        self.callback = callback
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.speech_threshold = 160.0   # RMS threshold
        self.silence_duration = 1.35    # 1.35s silence to finalize
        self.min_speech_duration = 0.45 # Min seconds of speech
        self.vad = SileroVAD()
        self.use_neural_vad = True

    def start(self, callback: Optional[Callable[[bytes], None]] = None):
        """Start listening to system audio in background thread."""
        with self._lock:
            if callback:
                self.callback = callback

            if self.is_running and self._thread and self._thread.is_alive():
                logger.info("Loopback listener is already running.")
                return True

            self.is_running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.5)

            self.is_running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            logger.info("System Audio Loopback Listener started successfully.")
            return True

    def stop(self):
        """Stop listening to system audio."""
        with self._lock:
            self.is_running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.5)
            self._thread = None
            logger.info("System Audio Loopback Listener stopped.")

    def _capture_loop(self):
        """Background worker: capture audio from PulseAudio monitor source."""
        try:
            import pyaudio
        except ImportError:
            logger.error(
                "pyaudio not installed. Run: pip install pyaudio\n"
                "Also install system lib: sudo apt install portaudio19-dev"
            )
            self.is_running = False
            return

        p = pyaudio.PyAudio()
        stream = None

        try:
            monitor_name = _get_default_monitor_source()
            device_index = _find_pyaudio_monitor_index(p, monitor_name)

            if device_index is None:
                logger.error(
                    "Could not map the PulseAudio monitor source to a PortAudio input device.\n"
                    "Ensure the ALSA PulseAudio plugin is installed and PulseAudio or PipeWire-pulse is running.\n"
                    "Tip: pactl list short sources | grep monitor"
                )
                self.is_running = False
                p.terminate()
                return

            device_info = p.get_device_info_by_index(device_index)
            rate = int(device_info.get("defaultSampleRate", 44100))
            channels = max(1, int(device_info.get("maxInputChannels", 2)))
            uses_alsa_pulse = str(device_info.get("name", "")).strip().lower() == "pulse"
            if uses_alsa_pulse:
                channels = min(channels, 2)
            chunk_size = 1024

            logger.info(
                f"🎧 Opening loopback stream on '{device_info['name']}' "
                f"at {rate}Hz, {channels} channels."
            )

            if uses_alsa_pulse:
                stream = _open_pyaudio_monitor_stream(
                    p,
                    pyaudio.paInt16,
                    device_index,
                    monitor_name,
                    channels,
                    rate,
                    chunk_size,
                )
            else:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=chunk_size,
                )

            accumulated_frames = []
            is_speaking = False
            silence_start: Optional[float] = None
            speech_start: Optional[float] = None

            # Pre-roll: ~0.35s of prior audio so first syllable is never cut
            pre_roll_buffer = deque(maxlen=16)
            vad_audio_buffer = np.zeros(0, dtype=np.float32)

            while self.is_running:
                try:
                    raw_data = stream.read(chunk_size, exception_on_overflow=False)
                except Exception:
                    continue

                if not raw_data:
                    continue

                data_np = np.frombuffer(raw_data, dtype=np.int16)
                if len(data_np) == 0:
                    continue

                # Downsample and convert to mono float32 for Silero VAD
                if channels > 1:
                    mono_16 = data_np.reshape(-1, channels).mean(axis=1).astype(np.int16)
                else:
                    mono_16 = data_np

                # Resample mono audio to 16kHz for VAD
                if rate != 16000:
                    num_16k_samples = max(1, int(len(mono_16) * 16000 / rate))
                    idx_16k = np.linspace(0, len(mono_16) - 1, num_16k_samples).astype(np.int64)
                    mono_16k = mono_16[idx_16k]
                else:
                    mono_16k = mono_16

                mono_float = mono_16k.astype(np.float32) / 32768.0
                vad_audio_buffer = np.concatenate([vad_audio_buffer, mono_float])

                # Dual-Detection: Neural VAD + RMS Energy
                rms = float(np.sqrt(np.mean(data_np.astype(np.float64)**2)))
                rms_speech = rms > self.speech_threshold

                vad_speech = False
                while len(vad_audio_buffer) >= 512:
                    chunk_512 = vad_audio_buffer[:512]
                    vad_audio_buffer = vad_audio_buffer[512:]
                    if self.use_neural_vad and self.vad.session is not None:
                        if self.vad.is_speech(chunk_512, threshold=0.28):
                            vad_speech = True

                speech_detected = vad_speech or rms_speech
                now = time.time()

                if speech_detected:
                    if not is_speaking:
                        is_speaking = True
                        speech_start = now
                        accumulated_frames = list(pre_roll_buffer)
                        pre_roll_buffer.clear()
                    silence_start = None
                    accumulated_frames.append(raw_data)
                elif is_speaking:
                    accumulated_frames.append(raw_data)
                    if silence_start is None:
                        silence_start = now
                    elif now - silence_start >= self.silence_duration:
                        total_speech_time = (now - speech_start) if speech_start else 0.0
                        if total_speech_time >= self.min_speech_duration:
                            logger.info(
                                f"🎧 Interviewer speech detected! "
                                f"Duration: {total_speech_time:.2f}s. Processing..."
                            )
                            wav_bytes = self._encode_to_wav(accumulated_frames, channels, rate)
                            if self.callback and wav_bytes:
                                try:
                                    self.callback(wav_bytes)
                                except Exception as cb_err:
                                    logger.error(f"Error in speech callback: {cb_err}")

                        is_speaking = False
                        silence_start = None
                        speech_start = None
                        accumulated_frames = []
                        vad_audio_buffer = np.zeros(0, dtype=np.float32)
                        self.vad.reset_states()
                else:
                    pre_roll_buffer.append(raw_data)

        except Exception as e:
            logger.error(f"Loopback audio capture exception: {e}")
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
            if threading.current_thread() == self._thread:
                self.is_running = False

    def _encode_to_wav(self, frames, channels: int, original_rate: int) -> bytes:
        """Convert raw int16 frames to pristine 16000Hz mono 16-bit WAV bytes."""
        try:
            raw_all = b"".join(frames)
            data_np = np.frombuffer(raw_all, dtype=np.int16)

            if channels > 1:
                data_np = data_np.reshape(-1, channels).mean(axis=1).astype(np.int16)

            if original_rate != 16000 and len(data_np) > 1:
                num_target_samples = int(len(data_np) * 16000 / original_rate)
                indices = np.linspace(0, len(data_np) - 1, num_target_samples).astype(np.int64)
                data_16k = data_np[indices]
            else:
                data_16k = data_np

            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(data_16k.tobytes())

            return buf.getvalue()
        except Exception as e:
            logger.error(f"Failed to encode audio frames to WAV: {e}")
            return b""
