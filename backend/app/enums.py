from enum import Enum


class FeedbackLanguage(str, Enum):
    """Language of the explanations in the end-of-session report.

    Corrected phrases are always in English, whatever this value is.
    """

    ES = "es"
    EN = "en"


class AnalysisDimension(str, Enum):
    """What a ``turn_analyses`` row measures."""

    GRAMMAR = "grammar"
    FLUENCY = "fluency"
    PRONUNCIATION = "pronunciation"


class AnalysisStatus(str, Enum):
    """Life of one analysis: queued, finished with a result, given up after the retries, or skipped.

    Both ``skipped_*`` states are final and are not failures: nothing went wrong, the analysis
    could not or should not run. Values are stored as strings (``String(32)``), not as a database
    enum, so adding a state never needs ``ALTER TYPE``.
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    # Free Azure quota for the month is (nearly) used up: no call was made.
    SKIPPED_QUOTA = "skipped_quota"
    # No stored audio (the session has no audio consent, or it was withdrawn): nothing to assess.
    SKIPPED_NO_AUDIO = "skipped_no_audio"
