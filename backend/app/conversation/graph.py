"""transcribe -> tutor_reply -> synthesize, run once per HTTP turn."""

from functools import lru_cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.conversation.nodes import make_synthesize, make_transcribe, make_tutor_reply
from app.conversation.state import ConversationState
from app.llm.base import LLMProvider
from app.stt import STTProvider
from app.tts import TTSProvider


@lru_cache
def get_checkpointer() -> BaseCheckpointSaver:
    """Single checkpointer shared by every request.

    In memory for now: it is lost on restart and not shared between workers.
    To move to Postgres, return a ``langgraph.checkpoint.postgres.PostgresSaver``
    (or its async variant) here; nothing else changes. The turns table, not the
    checkpointer, is the source of truth for the history (see sessions_api).
    """
    return InMemorySaver()


def build_graph(
    stt: STTProvider,
    llm: LLMProvider,
    tts: TTSProvider,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    audio_dir: str | None = None,
) -> CompiledStateGraph:
    builder = StateGraph(ConversationState)
    builder.add_node("transcribe", make_transcribe(stt))
    builder.add_node("tutor_reply", make_tutor_reply(llm))
    builder.add_node("synthesize", make_synthesize(tts, audio_dir or settings.sessions_audio_dir))
    builder.add_edge(START, "transcribe")
    builder.add_edge("transcribe", "tutor_reply")
    builder.add_edge("tutor_reply", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile(checkpointer=checkpointer if checkpointer is not None else get_checkpointer())
