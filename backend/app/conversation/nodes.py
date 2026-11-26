"""Graph nodes. Each one returns only the state fields it changes."""

import logging
from collections.abc import Callable
from pathlib import Path

from app.conversation.state import ConversationState, Message
from app.llm.base import LLMProvider
from app.llm.schemas import TutorReply
from app.prompts import load_prompt
from app.providers.errors import TTSExhausted
from app.safety.guard import guard_reply
from app.safety.moderation import Moderator
from app.safety.text import untrusted
from app.stt import STTProvider
from app.stt.errors import NoSpeechError
from app.tts import TTSProvider
from app.tts.audio import wav_duration_seconds

logger = logging.getLogger("app.conversation")

Node = Callable[[ConversationState], dict]

TUTOR_PROMPT_VERSION = 4
# What the learner writes for the scene and the part: the same limit the API accepts.
SCENE_MAX_CHARS = 200
DEFAULT_ROLE = "a friendly English tutor who chats with the learner."


def make_transcribe(stt: STTProvider) -> Node:
    def transcribe(state: ConversationState) -> dict:
        # What Guako just said is the context that tells the recognizer which words are likely.
        last_tutor = next((m["content"] for m in reversed(state.get("messages", [])) if m["role"] == "assistant"), None)
        result = stt.transcribe(state["user_audio_path"], last_tutor)
        if not result.text.strip():
            raise NoSpeechError("No speech was detected in the audio")
        # Prefer the provider's duration; otherwise the end of the last word.
        seconds = result.duration if result.duration is not None else (result.words[-1].end if result.words else 0.0)
        return {
            "user_transcript": result.text.strip(),
            "user_words": [word.model_dump() for word in result.words],
            "user_audio_seconds": seconds,
            "user_stt_confidence": result.confidence,
            "user_no_speech_prob": result.no_speech_prob,
        }

    return transcribe


def tutor_system_prompt(level: str, topic: str, role: str | None) -> str:
    """The tutor's instructions. The scene and the part are the learner's text: neutralised before they go in."""
    return load_prompt(
        "tutor",
        TUTOR_PROMPT_VERSION,
        level=level,
        topic=untrusted(topic, max_chars=SCENE_MAX_CHARS),
        role=untrusted(role, max_chars=SCENE_MAX_CHARS) or DEFAULT_ROLE,
    )


def _format_history(messages: list[Message], learner_text: str) -> str:
    """LLMProvider takes one prompt string, so the history goes inside it.

    Everything the learner said is neutralised, and the new message goes inside <learner_message>: the
    prompt treats it as speech to answer, never as instructions.
    """
    lines = ["Conversation so far:"]
    for message in messages:
        speaker = "Learner" if message["role"] == "user" else "Guako"
        lines.append(f"{speaker}: {untrusted(message['content'])}")
    lines.append("")
    lines.append(f"<learner_message>{untrusted(learner_text)}</learner_message>")
    lines.append("Write Guako's next reply.")
    return "\n".join(lines)


def make_tutor_reply(llm: LLMProvider) -> Node:
    def tutor_reply(state: ConversationState) -> dict:
        system = tutor_system_prompt(state["level"], state["topic"], state.get("role"))
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


def make_guard(moderator: Moderator | None = None) -> Node:
    """Checks the learner's words and the reply before the voice: may replace the reply with a safe line."""

    def guard(state: ConversationState) -> dict:
        result = guard_reply(
            state["user_transcript"], state["reply_text"], prompt=("tutor", TUTOR_PROMPT_VERSION), moderator=moderator
        )
        update: dict = {"safety_events": result.events}
        if result.reply != state["reply_text"]:
            messages = list(state.get("messages", []))
            if messages and messages[-1]["role"] == "assistant":
                messages[-1] = {"role": "assistant", "content": result.reply}
            update |= {"reply_text": result.reply, "messages": messages}
        return update

    return guard


def make_synthesize(tts: TTSProvider, audio_dir: str) -> Node:
    def synthesize(state: ConversationState) -> dict:
        # turn_number was already incremented by tutor_reply, so it names this turn.
        output = Path(audio_dir) / str(state["session_id"]) / f"turn_{state['turn_number']:03d}_reply.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = tts.synthesize(state["reply_text"], str(output))
        except TTSExhausted:
            # Every voice provider is out: keep the turn without audio; the browser reads the text aloud.
            logger.warning("tts_degraded session=%s turn=%s voice=browser", state["session_id"], state["turn_number"])
            return {"reply_audio_path": "", "reply_audio_seconds": 0.0}
        return {
            "reply_audio_path": result.audio_path,
            "reply_audio_seconds": wav_duration_seconds(result.audio_path),
        }

    return synthesize
