"""Guako's first line: the tutor opens the scene in the part the learner chose.

It is saved as turn 0 of the session (no learner part), so replaying and reviewing the
conversation treat it like any other reply. Real turns start at 1.
"""

from dataclasses import dataclass
from pathlib import Path

from app.conversation.nodes import DEFAULT_ROLE, TUTOR_PROMPT_VERSION
from app.llm.base import LLMProvider
from app.llm.schemas import TutorReply
from app.prompts import load_prompt
from app.tts import TTSProvider
from app.tts.audio import wav_duration_seconds

OPENING_TURN = 0

_OPENING_PROMPT = (
    "Conversation so far: nothing yet.\n\n"
    "The learner has just arrived and has not said anything. Open the scene now: say your first line in "
    "your part, in 1 or 2 short sentences, and end with a question or a remark that invites them to answer."
)


@dataclass(frozen=True)
class Opening:
    reply_text: str
    reply_audio_path: str
    reply_audio_seconds: float


def generate_opening(
    llm: LLMProvider,
    tts: TTSProvider,
    *,
    session_id: int,
    level: str,
    topic: str,
    role: str | None,
    audio_dir: str,
) -> Opening:
    system = load_prompt(
        "tutor", TUTOR_PROMPT_VERSION, level=level, topic=topic, role=(role or "").strip() or DEFAULT_ROLE
    )
    reply = llm.generate(_OPENING_PROMPT, TutorReply, system=system).reply
    output = Path(audio_dir) / str(session_id) / f"turn_{OPENING_TURN:03d}_reply.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = tts.synthesize(reply, str(output))
    return Opening(reply, result.audio_path, wav_duration_seconds(result.audio_path))
