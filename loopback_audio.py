import os
import threading
import time
import io
import wave
import logging
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

class SystemAudioLoopback:
    def __init__(self, callback: Optional[Callable[[bytes], None]] = None):
        self.callback = callback
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.speech_threshold = 160.0  # RMS threshold for system playback
        self.silence_duration = 1.35   # 1.35s silence to finalize (natural pause allowance)
        self.min_speech_duration = 0.45 # Min seconds of speech to capture short questions
        self.vad = SileroVAD()
        self.use_neural_vad = True

    def get_loopback_device(self, p):
        """Find default WASAPI playback device's loopback endpoint."""
        try:
            import pyaudiowpatch as pyaudio
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info['defaultOutputDevice'])
            
            for dev in p.get_loopback_device_info_generator():
                if default_speakers['name'] in dev['name']:
                    return dev
            # Fallback to first available loopback device
            for dev in p.get_loopback_device_info_generator():
                return dev
        except Exception as e:
            logger.error(f"Error finding loopback device: {e}")
        return None

    def start(self, callback: Optional[Callable[[bytes], None]] = None):
        """Start listening to system audio in background thread."""
        with self._lock:
            if callback:
                self.callback = callback
                
            if self.is_running and self._thread and self._thread.is_alive():
                logger.info("Loopback listener is already running.")
                return True

            # If previous thread is still shutting down, wait for it
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
        """Background worker thread capturing audio chunks and detecting speech."""
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        stream = None

        try:
            device = self.get_loopback_device(p)
            if not device:
                logger.error("No WASAPI loopback device found on this system.")
                self.is_running = False
                p.terminate()
                return

            rate = int(device['defaultSampleRate'])
            channels = int(device['maxInputChannels'])
            chunk_size = 1024

            logger.info(f"Opening loopback stream on '{device['name']}' at {rate}Hz, {channels} channels.")

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device['index'],
                frames_per_buffer=chunk_size
            )

            accumulated_frames = []
            is_speaking = False
            silence_start: Optional[float] = None
            speech_start: Optional[float] = None

            # Pre-roll circular buffer keeps ~0.35s of prior audio so first syllables are never cut
            pre_roll_buffer = deque(maxlen=16)
            
            # Buffer for exact 512-sample chunks fed to Silero VAD
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

                # 1. Downsample and convert to mono float32 for Silero VAD
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

                # 2. Dual-Detection: Neural VAD + RMS Energy
                # When loopback speakers are silent, RMS is near 0. Speech typically > 160.
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
                        # Prepend pre-roll buffer so the beginning words ("What", "Explain", etc.) are intact
                        accumulated_frames = list(pre_roll_buffer)
                        pre_roll_buffer.clear()
                    silence_start = None
                    accumulated_frames.append(raw_data)
                elif is_speaking:
                    accumulated_frames.append(raw_data)
                    if silence_start is None:
                        silence_start = now
                    elif now - silence_start >= self.silence_duration:
                        # Finished speaking
                        total_speech_time = (now - speech_start) if speech_start else 0.0
                        if total_speech_time >= self.min_speech_duration:
                            logger.info(f"🎧 Interviewer speech detected! Total duration: {total_speech_time:.2f}s. Processing question...")
                            wav_bytes = self._encode_to_wav(accumulated_frames, channels, rate)
                            if self.callback and wav_bytes:
                                try:
                                    self.callback(wav_bytes)
                                except Exception as cb_err:
                                    logger.error(f"Error in speech callback: {cb_err}")

                        # Reset state
                        is_speaking = False
                        silence_start = None
                        speech_start = None
                        accumulated_frames = []
                        vad_audio_buffer = np.zeros(0, dtype=np.float32)
                        self.vad.reset_states()
                else:
                    # Keep rolling history while quiet
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
                # Average multi-channels to mono
                data_np = data_np.reshape(-1, channels).mean(axis=1).astype(np.int16)

            # High-fidelity linear resample to clean 16000Hz
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
