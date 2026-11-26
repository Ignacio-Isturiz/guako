from typing import Annotated

from pydantic import BaseModel, StringConstraints


class GrammarError(BaseModel):
    original: str
    correction: str
    error_type: str
    explanation: str


class GrammarAnalysis(BaseModel):
    errors: list[GrammarError]


class TutorReply(BaseModel):
    """Short spoken reply from the English tutor.

    Bounded: an empty or runaway answer (a model that starts reciting its instructions, for instance) fails
    validation and the provider is asked again.
    """

    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
