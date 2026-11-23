from pydantic import BaseModel


class GrammarError(BaseModel):
    original: str
    correction: str
    error_type: str
    explanation: str


class GrammarAnalysis(BaseModel):
    errors: list[GrammarError]
