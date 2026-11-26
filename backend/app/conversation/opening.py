"""Guako's first line: the tutor opens the scene in the part the learner chose.

It is saved as turn 0 of the session (no learner part), so replaying and reviewing the
conversation treat it like any other reply. Real turns start at 1.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.conversation.nodes import TUTOR_PROMPT_VERSION, tutor_system_prompt
from app.llm.base import LLMProvider
from app.llm.schemas import TutorReply
from app.providers.errors import TTSExhausted
from app.safety.guard import guard_reply
from app.safety.moderation import Moderator
from app.tts import TTSProvider
from app.tts.audio import wav_duration_seconds

OPENING_TURN = 0

_OPENING_PROMPT = (
    "Conversation so far: nothing yet.\n\n"
    "The learner has just arrived and has not said anything. Open the scene now: say your first line in "
    "your part, in 1 or 2 short sentences (15 words at most), and end with a question or a remark that invites them to answer."
)


@dataclass(frozen=True)
class Opening:
    reply_text: str
    reply_audio_path: str
    reply_audio_seconds: float
    safety_events: list[dict] = field(default_factory=list)


def generate_opening(
    llm: LLMProvider,
    tts: TTSProvider,
    *,
    session_id: int,
    level: str,
    topic: str,
    role: str | None,
    audio_dir: str,
    moderator: Moderator | None = None,
) -> Opening:
    system = tutor_system_prompt(level, topic, role)
    raw = llm.generate(_OPENING_PROMPT, TutorReply, system=system).reply
    guarded = guard_reply(None, raw, prompt=("tutor", TUTOR_PROMPT_VERSION), moderator=moderator)
    reply = guarded.reply
    output = Path(audio_dir) / str(session_id) / f"turn_{OPENING_TURN:03d}_reply.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = tts.synthesize(reply, str(output))
    except TTSExhausted:
        # Every voice provider is out: the opening is saved without audio and the browser reads it aloud.
        return Opening(reply, "", 0.0, guarded.events)
    return Opening(reply, result.audio_path, wav_duration_seconds(result.audio_path), guarded.events)
