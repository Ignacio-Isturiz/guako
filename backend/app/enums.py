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


class AnalysisStatus(str, Enum):
    """Life of one analysis: queued, finished with a result, or given up after the retries."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
