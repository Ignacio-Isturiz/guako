"""POST /api/grammar/analyze  { text } → { errors: [...] }  (requires login)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db import User
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.llm.schemas import GrammarAnalysis
from app.prompts import load_prompt
from app.users import current_active_user

router = APIRouter(prefix="/api/grammar", tags=["grammar"])


class GrammarRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/analyze", response_model=GrammarAnalysis)
def analyze(
    body: GrammarRequest,
    _user: Annotated[User, Depends(current_active_user)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> GrammarAnalysis:
    prompt = load_prompt("grammar_analysis", 1, text=body.text)
    return llm.generate(prompt, GrammarAnalysis)
