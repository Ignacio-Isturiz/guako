"""Prepares a recording so every Whisper provider can read it.

iOS (Safari and the app's WKWebView) records with MediaRecorder in its own way (fragmented MP4 with AAC, or a
WebM on recent versions) and Groq has answered HTTP 400 to those recordings while Android's are fine. ffmpeg
re-encodes a recording to FLAC mono 16 kHz, which is what Whisper works with internally: nothing is lost and
the upload is smaller.
"""

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("app.stt")

# Containers only iOS sends: converted before the first try, to save the provider's 400 on every turn.
CONVERT_FIRST: frozenset[str] = frozenset({".mp4", ".m4a"})

FFMPEG_TIMEOUT_SECONDS = 30


@contextmanager
def as_flac(audio_path: str) -> Iterator[str | None]:
    """Yield a FLAC mono 16 kHz copy of the recording, removed afterwards; None if ffmpeg is missing or fails."""
    path = Path(audio_path)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.warning("stt_convert_skipped reason=ffmpeg_missing file=%s", path.name)
        yield None
        return
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"{path.stem}.flac"
        try:
            subprocess.run(
                # -vn: a recording can carry an empty video track; only the sound matters
                [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(target)],
                capture_output=True,
                timeout=FFMPEG_TIMEOUT_SECONDS,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("stt_convert_failed file=%s error=%s", path.name, type(exc).__name__)
            yield None
            return
        yield str(target)
