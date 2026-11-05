from io import BytesIO
from pathlib import Path
import wave

import pytest

from backend.interview_voice import (
    InterviewVoiceUnavailableError,
    LocalKokoroInterviewVoice,
    _pcm_wav,
)


def test_pcm_wav_encodes_mono_audio_without_external_tools():
    audio = _pcm_wav([0.0, 0.5, -0.5], 24_000)
    with wave.open(BytesIO(audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        assert wav.getnframes() == 3


def test_local_voice_fails_safely_when_model_files_are_missing(tmp_path: Path):
    voice = LocalKokoroInterviewVoice(
        model_path=tmp_path / "missing.onnx",
        voices_path=tmp_path / "missing.bin",
    )
    with pytest.raises(InterviewVoiceUnavailableError, match="not configured"):
        voice.synthesize("Tell me about your experience.")


def test_local_voice_reuses_generated_question_audio(tmp_path: Path):
    class FakeKokoro:
        calls = 0

        def create(self, *args, **kwargs):
            self.calls += 1
            return [0.0, 0.25, -0.25], 24_000

    voice = LocalKokoroInterviewVoice(
        model_path=tmp_path / "unused.onnx",
        voices_path=tmp_path / "unused.bin",
    )
    engine = FakeKokoro()
    voice._engine = engine

    first = voice.synthesize("Tell me about your experience.")
    second = voice.synthesize("Tell me about your experience.")

    assert first == second
    assert engine.calls == 1
