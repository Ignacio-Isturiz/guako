"""The analysis of one turn as a LangGraph graph: what runs, in what order, what in parallel.

    START -> load -> [fluency | grammar] -> merge -> triage -> [pronunciation | judge] -> persist -> END

Phase 1 (fluency, grammar) has no dependencies. ``merge`` collects what the grammar analysis found out the
learner MEANT (the recognizer may have written another word that sounds alike); phase 2 needs it: pronunciation
is scored against that text and the judge reads it. ``triage`` decides what the judge does not need to see (a
trivial turn, or no previous message from the tutor to compare with). Only the dimensions still ``pending`` are
launched (dynamic fan-out with ``Send``), so the retrier reuses this same graph without redoing what is done.

Rules of the graph:
- A node NEVER raises. It returns an outcome (done, failed, deferred or skipped_*), because in LangGraph a
  branch that fails for good aborts the whole run and discards its siblings' results (checked on
  langgraph 1.2.24): a grammar failure must not lose the fluency. That is why the retries with growing waits
  stay inside the nodes (runner.py) and ``RetryPolicy`` is not used on them.
- ``deferred`` means "nobody could answer right now" (every provider out): the row stays ``pending`` and the
  retrier picks it up later.
- ``turn_analyses`` stays the source of truth. The graph only decides and computes; ``persist`` is the single
  fan-in that writes the outcomes, in one transaction.
"""

import logging
from typing import Annotated, Any, TypedDict

from fastapi.concurrency import run_in_threadpool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis import runner
from app.analysis.fluency import analyze_fluency
from app.analysis.judge import is_trivial
from app.db import ConversationSession, Turn, TurnAnalysis, User
from app.enums import AnalysisDimension as Dim
from app.enums import AnalysisStatus as Status
from app.llm.base import LLMProvider
from app.llm.errors import LLMError
from app.providers.context import set_call_context
from app import rag
from app.providers.errors import LLMExhausted
from app.pronunciation import PronunciationError, PronunciationProvider
from app.rag.memory import events_from, record_events
from app.rag.retrieve import attach_rules
from app.stt import WordTiming

logger = logging.getLogger("app.analysis")

DEFERRED = "deferred"  # not a stored status: the row simply stays pending
JUDGE_DIMENSIONS = (Dim.COMMUNICATION.value, Dim.LISTENING.value)


def _merge(current: dict | None, update: dict) -> dict:
    """Reducer: every branch reports its own dimensions; the results are put together."""
    return {**(current or {}), **update}


async def _with_rules(maker: async_sessionmaker[AsyncSession], result: dict) -> tuple[dict, list[dict]]:
    """RAG: each error gets the rule of the corpus that explains it, and the learner's memory gets its events.

    Returns the result and the memory events to save with it. Off (no events) without an embedding key or
    outside PostgreSQL.
    """
    embedder = rag.get_embedder()
    if embedder is None or maker.kw["bind"].dialect.name != "postgresql":
        return result, []
    vectors: list[list[float]] = []
    result = await attach_rules(maker, embedder, result, vectors_out=vectors)
    return result, events_from(result, vectors)


class AnalysisState(TypedDict, total=False):
    turn_id: int
    ctx: dict[str, Any]  # plain data of the turn (never ORM objects: branches run concurrently)
    pending: list[str]  # dimensions still to do
    intended: dict | None  # what the learner meant, from the grammar analysis
    events: list[dict]  # the grammar errors as memory events (RAG 2), saved with the grammar result
    outcomes: Annotated[dict[str, dict], _merge]  # dimension -> {"status", "result", "error"}


def _outcome(status: str, result: dict | None = None, error: str | None = None) -> dict:
    return {"status": status, "result": result, "error": error}


async def _guard(turn_id: int, dimensions: tuple[str, ...], work) -> dict[str, dict]:  # noqa: ANN001
    """Run the work of one or more dimensions and turn ANY failure into outcomes, so a node never raises.

    ``work`` returns {dimension: (status, result, error)}.
    """
    try:
        done = await work()
    except LLMExhausted as exc:
        # Not a failure: nobody could answer right now. The rows stay pending for the retrier.
        logger.warning("analysis_deferred turn=%s dimensions=%s retry_after=%s", turn_id, ",".join(dimensions), exc.retry_after)
        return {d: _outcome(DEFERRED) for d in dimensions}
    except Exception as exc:
        code = exc.code if isinstance(exc, (LLMError, PronunciationError)) else type(exc).__name__
        logger.warning("analysis_failed turn=%s dimensions=%s error=%s", turn_id, ",".join(dimensions), code)
        return {d: _outcome(Status.FAILED.value, None, str(code)[:200]) for d in dimensions}
    return {d: _outcome(*done[d]) for d in dimensions}


def build_analysis_graph(
    maker: async_sessionmaker[AsyncSession],
    llm: LLMProvider,
    pronunciation: PronunciationProvider | None,
) -> CompiledStateGraph:
    """The graph for one run. The providers are captured here; nothing is global."""

    def todo(state: AnalysisState, *dimensions: str) -> list[str]:
        return [d for d in dimensions if d in state.get("pending", [])]

    def judge_todo(state: AnalysisState) -> list[str]:
        """Judge dimensions still pending and not already settled (skipped) by the triage."""
        decided = state.get("outcomes", {})
        return [d for d in todo(state, *JUDGE_DIMENSIONS) if d not in decided]

    # --- nodes ---------------------------------------------------------------------------------

    async def load(state: AnalysisState) -> dict:
        async with maker() as db:
            turn = await db.get(Turn, state["turn_id"])
            if turn is None:
                return {"pending": [], "ctx": {}}
            rows = (
                await db.scalars(
                    select(TurnAnalysis.dimension).where(
                        TurnAnalysis.turn_id == turn.id, TurnAnalysis.status == Status.PENDING.value
                    )
                )
            ).all()
            session = await db.get(ConversationSession, turn.session_id)
            user = await db.get(User, session.user_id) if session else None
            ctx = {
                "session_id": turn.session_id,
                "user_id": session.user_id if session else None,
                "turn_number": turn.turn_number,
                "transcript": turn.user_transcript or "",
                "words": turn.word_timestamps or [],
                "tutor_prev": await runner._previous_tutor_text(db, turn),
                "level": session.level if session else "",
                "topic": session.topic if session else "",
                "feedback_language": user.feedback_language.value if user else "es",
                "stt_confidence": turn.stt_confidence,
                "stt_no_speech_prob": turn.stt_no_speech_prob,
            }
        return {"ctx": ctx, "pending": list(rows)}

    async def fluency(state: AnalysisState) -> dict:
        ctx = state["ctx"]

        async def work() -> dict:
            words = [WordTiming.model_validate(w) for w in ctx["words"]]
            return {Dim.FLUENCY.value: (Status.DONE.value, analyze_fluency(words), None)}

        return {"outcomes": await _guard(state["turn_id"], (Dim.FLUENCY.value,), work)}

    async def grammar(state: AnalysisState) -> dict:
        ctx = state["ctx"]
        set_call_context(session_id=ctx["session_id"], turn_id=state["turn_id"])  # provider_calls: which turn it served

        async def work() -> dict:
            if not ctx["transcript"].strip():  # nothing said, nothing to ask the LLM
                return {Dim.GRAMMAR.value: (Status.DONE.value, {"errors": [], "discarded_low_confidence": 0}, None)}
            result = await run_in_threadpool(runner._generate_with_backoff, llm, ctx["transcript"], ctx["tutor_prev"])
            result, events = await _with_rules(maker, result)
            memory["events"] = events
            return {Dim.GRAMMAR.value: (Status.DONE.value, result, None)}

        memory: dict = {}  # filled by work(); the events travel in the state next to the outcome
        outcomes = await _guard(state["turn_id"], (Dim.GRAMMAR.value,), work)
        return {"outcomes": outcomes, "events": memory.get("events", [])}

    async def merge(state: AnalysisState) -> dict:
        """Fan-in of phase 1: what the learner meant, for the nodes of phase 2."""
        grammar_outcome = state.get("outcomes", {}).get(Dim.GRAMMAR.value)
        if grammar_outcome is not None:
            result = grammar_outcome["result"] if grammar_outcome["status"] == Status.DONE.value else None
            if result and result.get("intended_text"):
                return {"intended": {"text": result["intended_text"], "fixes": result.get("heard_fixes", [])}}
            return {"intended": None}
        # The grammar was not part of this run: it may have been finished by an earlier one.
        async with maker() as db:
            turn = await db.get(Turn, state["turn_id"])
            return {"intended": await runner._intended(db, turn) if turn else None}

    async def triage(state: AnalysisState) -> dict:
        """What the judge does not need to see: a trivial turn, or a listening with nothing to compare with."""
        ctx = state["ctx"]
        pending = todo(state, *JUDGE_DIMENSIONS)
        if pending and is_trivial(ctx["transcript"]):
            return {"outcomes": {d: _outcome(Status.SKIPPED_TRIVIAL.value) for d in pending}}
        if Dim.LISTENING.value in pending and not ctx["tutor_prev"].strip():
            return {"outcomes": {Dim.LISTENING.value: _outcome(Status.SKIPPED_NO_CONTEXT.value)}}
        return {}

    async def pronunciation_node(state: AnalysisState) -> dict:
        ctx = state["ctx"]
        set_call_context(session_id=ctx["session_id"], turn_id=state["turn_id"])

        async def work() -> dict:
            async with maker() as db:  # its own session: branches never share one
                turn = await db.get(Turn, state["turn_id"])
                return {Dim.PRONUNCIATION.value: await runner._assess_pronunciation(db, turn, pronunciation, state.get("intended"))}

        return {"outcomes": await _guard(state["turn_id"], (Dim.PRONUNCIATION.value,), work)}

    async def judge(state: AnalysisState) -> dict:
        """One call for both dimensions; each one still gets its own row."""
        ctx, dimensions = state["ctx"], tuple(judge_todo(state))
        want_listening = Dim.LISTENING.value in dimensions
        set_call_context(session_id=ctx["session_id"], turn_id=state["turn_id"])

        async def work() -> dict:
            result = await run_in_threadpool(runner._judge_with_backoff, llm, ctx, want_listening, state.get("intended"))
            done: dict = {}
            if Dim.COMMUNICATION.value in dimensions:
                done[Dim.COMMUNICATION.value] = (Status.DONE.value, result["communication"], None)
            if want_listening:
                listening = result["listening"]
                done[Dim.LISTENING.value] = (
                    (Status.DONE.value, listening, None) if listening is not None else (Status.FAILED.value, None, "no_listening_score")
                )
            return done

        return {"outcomes": await _guard(state["turn_id"], dimensions, work)}

    async def persist(state: AnalysisState) -> dict:
        """The single fan-in: write every outcome in one transaction. A deferred one leaves its row pending."""
        outcomes = state.get("outcomes", {})
        async with maker() as db:
            rows = (
                await db.scalars(
                    select(TurnAnalysis).where(
                        TurnAnalysis.turn_id == state["turn_id"], TurnAnalysis.status == Status.PENDING.value
                    )
                )
            ).all()
            for row in rows:
                outcome = outcomes.get(row.dimension)
                if outcome is None or outcome["status"] == DEFERRED:
                    continue
                row.status, row.result, row.error = outcome["status"], outcome["result"], outcome["error"]
                if row.dimension == Dim.GRAMMAR.value and outcome["status"] == Status.DONE.value and state.get("events") is not None:
                    ctx = state["ctx"]
                    if ctx.get("user_id") is not None and (state["events"] or (outcome["result"] or {}).get("errors") == []):
                        await record_events(
                            db, user_id=ctx["user_id"], session_id=ctx["session_id"], turn_id=state["turn_id"],
                            events=state["events"],
                        )
            await db.commit()
        return {}

    # --- routing -------------------------------------------------------------------------------

    def after_load(state: AnalysisState) -> list[Send] | str:
        """Phase 1: one task per pending independent dimension (dynamic fan-out)."""
        sends = [Send(d, state) for d in todo(state, Dim.FLUENCY.value, Dim.GRAMMAR.value)]
        return sends or "merge"

    def after_triage(state: AnalysisState) -> list[Send] | str:
        """Phase 2: the dimensions that needed the grammar's findings, in parallel."""
        sends = [Send(d, state) for d in todo(state, Dim.PRONUNCIATION.value)]
        if judge_todo(state):
            sends.append(Send("judge", state))
        return sends or "persist"

    graph = StateGraph(AnalysisState)
    graph.add_node("load", load)
    graph.add_node("fluency", fluency)
    graph.add_node("grammar", grammar)
    graph.add_node("merge", merge)
    graph.add_node("triage", triage)
    graph.add_node("pronunciation", pronunciation_node)
    graph.add_node("judge", judge)
    graph.add_node("persist", persist)
    graph.add_edge(START, "load")
    graph.add_conditional_edges("load", after_load, ["fluency", "grammar", "merge"])
    graph.add_edge("fluency", "merge")
    graph.add_edge("grammar", "merge")
    graph.add_edge("merge", "triage")
    graph.add_conditional_edges("triage", after_triage, ["pronunciation", "judge", "persist"])
    graph.add_edge("pronunciation", "persist")
    graph.add_edge("judge", "persist")
    graph.add_edge("persist", END)
    return graph.compile()
