"""Graph nodes. Each one returns only the state fields it changes."""

from collections.abc import Callable
from pathlib import Path

from app.conversation.state import ConversationState, Message
from app.llm.base import LLMProvider
from app.llm.schemas import TutorReply
from app.prompts import load_prompt
from app.stt import STTProvider
from app.stt.errors import NoSpeechError
from app.tts import TTSProvider
from app.tts.audio import wav_duration_seconds

Node = Callable[[ConversationState], dict]

TUTOR_PROMPT_VERSION = 1


def make_transcribe(stt: STTProvider) -> Node:
    def transcribe(state: ConversationState) -> dict:
        result = stt.transcribe(state["user_audio_path"])
        if not result.text.strip():
            raise NoSpeechError("No speech was detected in the audio")
        # Prefer the provider's duration; otherwise the end of the last word.
        seconds = result.duration if result.duration is not None else (result.words[-1].end if result.words else 0.0)
        return {
            "user_transcript": result.text.strip(),
            "user_words": [word.model_dump() for word in result.words],
            "user_audio_seconds": seconds,
        }

    return transcribe


def _format_history(messages: list[Message], learner_text: str) -> str:
    """LLMProvider takes one prompt string, so the history goes inside it."""
    lines = ["Conversation so far:"]
    for message in messages:
        speaker = "Learner" if message["role"] == "user" else "Guako"
        lines.append(f"{speaker}: {message['content']}")
    lines.append("")
    lines.append(f"Learner's new message: {learner_text}")
    lines.append("Write Guako's next reply.")
    return "\n".join(lines)


def make_tutor_reply(llm: LLMProvider) -> Node:
    def tutor_reply(state: ConversationState) -> dict:
        system = load_prompt("tutor", TUTOR_PROMPT_VERSION, level=state["level"], topic=state["topic"])
        history = state.get("messages", [])
        learner_text = state["user_transcript"]
        reply = llm.generate(_format_history(history, learner_text), TutorReply, system=system).reply
        return {
            "reply_text": reply,
            "turn_number": state["turn_number"] + 1,
            "messages": [
                *history,
                {"role": "user", "content": learner_text},
                {"role": "assistant", "content": reply},
            ],
        }

    return tutor_reply


def make_synthesize(tts: TTSProvider, audio_dir: str) -> Node:
    def synthesize(state: ConversationState) -> dict:
        # turn_number was already incremented by tutor_reply, so it names this turn.
        output = Path(audio_dir) / str(state["session_id"]) / f"turn_{state['turn_number']:03d}_reply.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        result = tts.synthesize(state["reply_text"], str(output))
        return {
            "reply_audio_path": result.audio_path,
            "reply_audio_seconds": wav_duration_seconds(result.audio_path),
        }

    return synthesize
