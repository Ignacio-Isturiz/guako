from typing import TypedDict


class Message(TypedDict):
    """One line of the conversation. ``role`` is "user" or "assistant"."""

    role: str
    content: str


class ConversationState(TypedDict, total=False):
    """State of one session, handed to the graph on every turn.

    Holds file paths, never audio bytes. ``total=False`` because nodes return
    partial updates and the first turn starts without the reply fields.
    """

    session_id: int
    level: str
    topic: str
    # Number of completed turns; tutor_reply increments it.
    turn_number: int
    messages: list[Message]
    user_audio_path: str
    user_transcript: str
    # Per-word timings of the user's speech (WordTiming dumps), kept for pronunciation work.
    user_words: list[dict]
    # Seconds of audio, counted against the daily limit.
    user_audio_seconds: float
    reply_text: str
    reply_audio_path: str
    reply_audio_seconds: float
