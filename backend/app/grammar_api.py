"""POST /api/grammar/analyze  { text } → { errors: [...] }  (requires login)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db import User
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.llm.schemas import GrammarAnalysis
from app.prompts import load_prompt
from app.safety.text import untrusted
from app.consents import user_with_terms

router = APIRouter(prefix="/api/grammar", tags=["grammar"])


class GrammarRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/analyze", response_model=GrammarAnalysis)
def analyze(
    body: GrammarRequest,
    _user: Annotated[User, Depends(user_with_terms)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> GrammarAnalysis:
    prompt = load_prompt("grammar_analysis", 1, text=untrusted(body.text))
    return llm.generate(prompt, GrammarAnalysis)
