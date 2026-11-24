from app.config import settings
from app.tts.base import TTSProvider
from app.tts.cache import TTSCache
from app.tts.schemas import TTSResult


class CachedTTSProvider(TTSProvider):
    """Serves repeated texts from the file cache; otherwise calls the wrapped provider.

    Failures from the wrapped provider (TTSError) propagate unchanged and
    nothing is cached for them.
    """

    def __init__(self, provider: TTSProvider, *, cache: TTSCache | None = None) -> None:
        self._provider = provider
        self._cache = cache if cache is not None else TTSCache(settings.tts_cache_dir)
        self.name = provider.name
        self.voice = provider.voice

    def has_cached(self, text: str) -> bool:
        """True if ``text`` is in the cache: serving it costs nothing and uses no provider quota."""
        return self._cache.path_for(text, self.voice).is_file()

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        if self._cache.fetch(text, self.voice, output_path):
            return TTSResult(audio_path=output_path, provider=self.name, from_cache=True)

        result = self._provider.synthesize(text, output_path)
        self._cache.store(text, self.voice, output_path)
        return result
