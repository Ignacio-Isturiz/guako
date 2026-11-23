from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.conversation.graph import build_graph
from app.conversation.state import ConversationState
from app.stt.errors import NoSpeechError
from tests.fakes import FakeLLM, FakeSTT, FakeTTS


def _state(**overrides) -> ConversationState:  # type: ignore[no-untyped-def]
    state: ConversationState = {
        "session_id": 7,
        "level": "B1",
        "topic": "Travel",
        "turn_number": 0,
        "messages": [],
        "user_audio_path": "ignored-by-the-fake.wav",
    }
    state.update(overrides)
    return state


def _run(graph, state: ConversationState):  # type: ignore[no-untyped-def]
    return graph.invoke(state, {"configurable": {"thread_id": "7"}})


def test_graph_runs_the_three_nodes_in_order_and_updates_the_turn(tmp_path: Path) -> None:
    calls: list[str] = []
    llm = FakeLLM(calls)
    graph = build_graph(FakeSTT(calls), llm, FakeTTS(calls), checkpointer=InMemorySaver(), audio_dir=str(tmp_path))

    result = _run(graph, _state())

    assert calls == ["stt", "llm", "tts"]
    assert result["turn_number"] == 1
    assert result["user_transcript"] == "I like to travel by train"
    assert result["reply_text"] == "That sounds fun! Where do you go?"
    assert Path(result["reply_audio_path"]).is_file()
    assert result["messages"] == [
        {"role": "user", "content": "I like to travel by train"},
        {"role": "assistant", "content": "That sounds fun! Where do you go?"},
    ]
    assert len(result["user_words"]) == 6


def test_tutor_prompt_carries_level_topic_and_history(tmp_path: Path) -> None:
    calls: list[str] = []
    llm = FakeLLM(calls)
    graph = build_graph(FakeSTT(calls), llm, FakeTTS(calls), checkpointer=InMemorySaver(), audio_dir=str(tmp_path))
    history = [
        {"role": "user", "content": "Hello Guako"},
        {"role": "assistant", "content": "Hi! Where would you like to travel?"},
    ]

    result = _run(graph, _state(turn_number=1, messages=history))

    assert result["turn_number"] == 2
    assert "Hi! Where would you like to travel?" in llm.prompts[0]
    assert "I like to travel by train" in llm.prompts[0]
    assert llm.systems[0] is not None
    assert "B1" in llm.systems[0] and "Travel" in llm.systems[0]
    assert Path(result["reply_audio_path"]).name == "turn_002_reply.wav"


def test_silence_stops_the_graph_before_the_llm(tmp_path: Path) -> None:
    calls: list[str] = []
    graph = build_graph(
        FakeSTT(calls, text="   "), FakeLLM(calls), FakeTTS(calls), checkpointer=InMemorySaver(), audio_dir=str(tmp_path)
    )

    with pytest.raises(NoSpeechError):
        _run(graph, _state())

    assert calls == ["stt"]
