"""Fake STT/LLM/TTS providers: no network, record what they were called with."""

import wave
from pathlib import Path

from pydantic import BaseModel

from app.stt import STTProvider, TranscriptionResult, WordTiming
from app.tts import TTSProvider, TTSResult


class FakeSTT(STTProvider):
    def __init__(self, calls: list[str], text: str = "I like to travel by train", error: Exception | None = None) -> None:
        self.calls = calls
        self.text = text
        self.error = error
        self.contexts: list[str | None] = []

    def transcribe(self, audio_path: str, context: str | None = None) -> TranscriptionResult:
        self.contexts.append(context)
        self.calls.append("stt")
        if self.error:
            raise self.error
        words = [WordTiming(word=w, start=i * 0.4, end=i * 0.4 + 0.3) for i, w in enumerate(self.text.split())]
        return TranscriptionResult(text=self.text, language="english", duration=2.5, words=words)


class FakeLLM:
    """Satisfies the LLMProvider protocol; keeps every prompt it receives."""

    def __init__(self, calls: list[str], reply: str = "That sounds fun! Where do you go?", error: Exception | None = None) -> None:
        self.calls = calls
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    @property
    def tutor_prompts(self) -> list[str]:
        """The prompts of the conversation itself, without the background grammar analyses."""
        return [p for p in self.prompts if "Learner text:" not in p]

    def generate(self, prompt: str, response_model: type[BaseModel], *, system: str | None = None) -> BaseModel:
        self.calls.append("llm")
        self.prompts.append(prompt)
        self.systems.append(system)
        if self.error:
            raise self.error
        if "errors" in response_model.model_fields:  # the background grammar analysis: no errors found
            return response_model(errors=[])
        return response_model(reply=self.reply)


class FakeTTS(TTSProvider):
    name = "fake"
    voice = "fake-voice"

    def __init__(self, calls: list[str], error: Exception | None = None) -> None:
        self.calls = calls
        self.error = error

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        self.calls.append("tts")
        if self.error:
            raise self.error
        # A real 1-second WAV (24 kHz, 16-bit, mono) so the duration can be measured.
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(output_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24_000)
            wav.writeframes(bytes(2 * 24_000))
        return TTSResult(audio_path=output_path, provider=self.name, from_cache=False)
