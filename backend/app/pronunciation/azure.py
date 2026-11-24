"""Pronunciation scoring with Azure Speech (REST API for short audio, Pronunciation Assessment).

Hosts are built from AZURE_SPEECH_REGION. The key is only ever sent in the request header and is
never logged or put in an error message.
"""

import base64
import json
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from app.config import settings
from app.pronunciation.base import PronunciationProvider
from app.pronunciation.errors import (
    PronunciationAudioError,
    PronunciationAuthError,
    PronunciationError,
    PronunciationNoSpeechError,
    PronunciationNotConfiguredError,
    PronunciationProviderError,
    PronunciationRateLimitError,
    PronunciationTimeoutError,
)
from app.pronunciation.schemas import PhonemeScore, PronunciationResult, WordScore

# Azure accepts at most 30 s for pronunciation assessment; 2 s of margin for the encoder's padding.
MAX_AUDIO_SECONDS = 28.0
_PATH = "/speech/recognition/conversation/cognitiveservices/v1"
_PARAMS = {"language": "en-US", "format": "detailed"}
_REGION = re.compile(r"^[a-z0-9]{2,40}$")
_FFMPEG_TIMEOUT_SECONDS = 30


# Azure's en-US phoneme alphabet (SAPI) -> IPA, so the app can show sounds learners can look up.
_SAPI_TO_IPA = {
    "aa": "ɑ", "ae": "æ", "ah": "ʌ", "ao": "ɔ", "aw": "aʊ", "ax": "ə", "axr": "ɚ", "ay": "aɪ",
    "b": "b", "ch": "tʃ", "d": "d", "dh": "ð", "eh": "ɛ", "er": "ɝ", "ey": "eɪ", "f": "f",
    "g": "ɡ", "h": "h", "ih": "ɪ", "iy": "i", "jh": "dʒ", "k": "k", "l": "l", "m": "m",
    "n": "n", "ng": "ŋ", "ow": "oʊ", "oy": "ɔɪ", "p": "p", "r": "ɹ", "s": "s", "sh": "ʃ",
    "t": "t", "th": "θ", "uh": "ʊ", "uw": "u", "v": "v", "w": "w", "y": "j", "z": "z", "zh": "ʒ",
}  # fmt: skip


class AzurePronunciationProvider(PronunciationProvider):
    max_audio_seconds = MAX_AUDIO_SECONDS

    def __init__(
        self,
        api_key: SecretStr | None = None,
        region: str | None = None,
        *,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        key = api_key if api_key is not None else settings.azure_speech_key
        region = (region if region is not None else settings.azure_speech_region).strip().lower()
        if key is None or not key.get_secret_value().strip():
            raise PronunciationNotConfiguredError("AZURE_SPEECH_KEY is not set")
        if not _REGION.fullmatch(region):
            raise PronunciationNotConfiguredError("AZURE_SPEECH_REGION is not set or is not a valid region name")
        self._key = key
        self._url = f"https://{region}.stt.speech.microsoft.com{_PATH}"
        self._timeout = timeout_seconds or settings.azure_speech_timeout_seconds
        self._client = client  # injected in tests (httpx.MockTransport): they never reach the network

    def score_turn(self, audio_path: str, reference_text: str) -> PronunciationResult:
        audio = _prepare_audio(Path(audio_path), self.max_audio_seconds)
        assessment = {
            "ReferenceText": reference_text,
            "GradingSystem": "HundredMark",
            "Granularity": "Phoneme",
            "Dimension": "Comprehensive",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self._key.get_secret_value(),
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
            "Pronunciation-Assessment": base64.b64encode(json.dumps(assessment).encode("utf-8")).decode("ascii"),
        }
        try:
            if self._client is not None:
                response = self._client.post(self._url, params=_PARAMS, headers=headers, content=audio)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(self._url, params=_PARAMS, headers=headers, content=audio)
        except httpx.TimeoutException as exc:
            raise PronunciationTimeoutError("Azure Speech timed out") from exc
        except httpx.HTTPError as exc:
            raise PronunciationProviderError(f"Azure Speech request failed: {type(exc).__name__}") from exc
        return _parse_response(response)


def _parse_response(response: httpx.Response) -> PronunciationResult:
    status = response.status_code
    if status == 429:
        raise PronunciationRateLimitError("Azure Speech rate limit (429)")
    if status >= 500:
        raise PronunciationProviderError(f"Azure Speech unavailable ({status})")
    if status in (401, 403):
        raise PronunciationAuthError(f"Azure Speech rejected the credentials ({status})")
    if status != 200:
        raise PronunciationError(f"Azure Speech rejected the request ({status})", code="azure_bad_request")
    try:
        data = response.json()
    except ValueError as exc:
        raise PronunciationProviderError("Azure Speech sent a response that is not JSON") from exc
    if data.get("RecognitionStatus") != "Success" or not data.get("NBest"):
        raise PronunciationNoSpeechError(f"Azure Speech recognised nothing ({data.get('RecognitionStatus')})")
    best = data["NBest"][0]
    return PronunciationResult(
        accuracy_score=_score(best, "AccuracyScore"),
        pron_score=_score(best, "PronScore"),
        words=[
            WordScore(
                word=str(w.get("Word", "")),
                accuracy=_score(w, "AccuracyScore") or 0.0,
                error_type=str(_field(w, "ErrorType") or "None"),
                phonemes=[
                    PhonemeScore(
                        phoneme=str(p.get("Phoneme", "")),
                        ipa=_SAPI_TO_IPA.get(str(p.get("Phoneme", "")).lower()),
                        accuracy=_score(p, "AccuracyScore") or 0.0,
                    )
                    for p in w.get("Phonemes", [])
                ],
            )
            for w in best.get("Words", [])
        ],
    )


def _field(item: dict[str, Any], name: str) -> Any:
    """The docs show scores either directly on the item or inside a PronunciationAssessment object."""
    if name in item:
        return item[name]
    return (item.get("PronunciationAssessment") or {}).get(name)


def _score(item: dict[str, Any], name: str) -> float | None:
    value = _field(item, name)
    return float(value) if isinstance(value, int | float) else None


def _prepare_audio(path: Path, max_seconds: float) -> bytes:
    """WAV PCM 16-bit 16 kHz mono, at most ``max_seconds`` long (what the REST API accepts).

    A WAV that already fits is sent as it is; anything else (the browser records webm/opus) goes
    through ffmpeg.
    """
    if not path.is_file():
        raise PronunciationAudioError("audio file not found")
    try:
        with wave.open(str(path), "rb") as wav:
            fits = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            fits = fits and wav.getnframes() / wav.getframerate() <= max_seconds
        if fits:
            return path.read_bytes()
    except (wave.Error, EOFError):
        pass  # not a plain PCM WAV: convert it

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PronunciationAudioError("ffmpeg is not installed", code="ffmpeg_missing")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audio.wav"
        command = [
            ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(path),
            "-t", f"{max_seconds:.2f}", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
        ]  # fmt: skip
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=_FFMPEG_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError) as exc:
            raise PronunciationAudioError(f"ffmpeg could not convert the audio ({type(exc).__name__})") from exc
        return out.read_bytes()
