from enum import Enum


class FeedbackLanguage(str, Enum):
    """Language of the explanations in the end-of-session report.

    Corrected phrases are always in English, whatever this value is.
    """

    ES = "es"
    EN = "en"
