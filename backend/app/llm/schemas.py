from pydantic import BaseModel


class GrammarError(BaseModel):
    original: str
    correction: str
    error_type: str
    explanation: str


class GrammarAnalysis(BaseModel):
    errors: list[GrammarError]


class TutorReply(BaseModel):
    """Short spoken reply from the English tutor."""

    reply: str
