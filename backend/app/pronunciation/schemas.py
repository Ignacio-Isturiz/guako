from pydantic import BaseModel


class PhonemeScore(BaseModel):
    phoneme: str  # provider alphabet (Azure: SAPI, e.g. "th", "ax"); not meant to be shown as is
    ipa: str | None = None  # the same sound in IPA, ready to show (None if the provider's symbol is unknown)
    accuracy: float  # 0-100


class WordScore(BaseModel):
    word: str
    accuracy: float  # 0-100
    error_type: str = "None"
    phonemes: list[PhonemeScore] = []


class PronunciationResult(BaseModel):
    """Provider-neutral result: nothing here says Azure."""

    accuracy_score: float | None  # 0-100, whole utterance
    pron_score: float | None  # 0-100, weighted overall score of the provider
    words: list[WordScore]
