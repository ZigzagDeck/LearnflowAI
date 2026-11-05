"""Optional zero-API-cost interviewer speech powered by local Kokoro ONNX."""

from __future__ import annotations

from array import array
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import sys
import threading
import wave

from .system_resources import available_memory_bytes


class InterviewVoiceUnavailableError(RuntimeError):
    """Raised when local interviewer speech is not ready to serve."""


class InterviewVoiceSynthesisError(RuntimeError):
    """Raised when local speech generation fails safely."""


def _pcm_wav(samples, sample_rate: int) -> bytes:
    if sample_rate <= 0:
        raise InterviewVoiceSynthesisError("The generated audio sample rate is invalid.")
    pcm = array(
        "h",
        (
            round(max(-1.0, min(1.0, float(sample))) * 32767)
            for sample in samples
        ),
    )
    if not pcm:
        raise InterviewVoiceSynthesisError("The local voice engine returned empty audio.")
    if sys.byteorder != "little":
        pcm.byteswap()
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


class LocalKokoroInterviewVoice:
    """Lazily load a local Kokoro model and serialize CPU inference calls."""

    def __init__(
        self,
        *,
        model_path: Path,
        voices_path: Path,
        voice: str = "af_heart",
        language: str = "en-us",
        speed: float = 1.08,
        minimum_free_mb: int = 768,
    ) -> None:
        self.model_path = model_path
        self.voices_path = voices_path
        self.voice = voice
        self.language = language
        self.speed = max(0.5, min(2.0, speed))
        self.minimum_free_mb = max(256, minimum_free_mb)
        self._engine = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def _load_engine(self):
        if self._engine is not None:
            return self._engine
        if not self.model_path.is_file() or not self.voices_path.is_file():
            raise InterviewVoiceUnavailableError(
                "Local interviewer voice model files are not configured."
            )
        available = available_memory_bytes()
        required = self.minimum_free_mb * 1024 * 1024
        if available is not None and available < required:
            raise InterviewVoiceUnavailableError(
                "The server does not have enough free memory for local interviewer audio."
            )
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise InterviewVoiceUnavailableError(
                "The local interviewer voice package is not installed."
            ) from exc
        try:
            self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        except Exception as exc:
            raise InterviewVoiceUnavailableError(
                "The local interviewer voice model could not be loaded."
            ) from exc
        return self._engine

    def synthesize(self, text: str) -> bytes:
        clean_text = " ".join(text.split())
        if not clean_text:
            raise InterviewVoiceSynthesisError("Interviewer text is empty.")
        if len(clean_text) > 1_500:
            raise InterviewVoiceSynthesisError("Interviewer text is too long for audio.")
        with self._lock:
            cached = self._cache.get(clean_text)
            if cached is not None:
                self._cache.move_to_end(clean_text)
                return cached
            engine = self._load_engine()
            try:
                samples, sample_rate = engine.create(
                    clean_text,
                    voice=self.voice,
                    speed=self.speed,
                    lang=self.language,
                )
                audio = _pcm_wav(samples, int(sample_rate))
                self._cache[clean_text] = audio
                while len(self._cache) > 8:
                    self._cache.popitem(last=False)
                return audio
            except (InterviewVoiceUnavailableError, InterviewVoiceSynthesisError):
                raise
            except Exception as exc:
                raise InterviewVoiceSynthesisError(
                    "The interviewer audio could not be generated."
                ) from exc

