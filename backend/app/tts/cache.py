import hashlib
import shutil
from pathlib import Path


class TTSCache:
    """File cache of synthesized WAVs, keyed by SHA-256 of voice + text.

    Saves quota: the Groq free tier allows only 100 requests/day per organization.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    def path_for(self, text: str, voice: str) -> Path:
        # NUL separator so ("ab", "c") and ("a", "bc") can never collide.
        digest = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()
        return self._dir / f"{digest}.wav"

    def fetch(self, text: str, voice: str, output_path: str) -> bool:
        """Copy the cached audio to ``output_path``. Returns False on a miss."""
        cached = self.path_for(text, voice)
        if not cached.is_file():
            return False
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out)
        return True

    def store(self, text: str, voice: str, audio_path: str) -> None:
        """Save a freshly synthesized file. Cache problems are never fatal."""
        target = self.path_for(text, voice)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(audio_path, target)
        except OSError:
            pass
