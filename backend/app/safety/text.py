"""Text that comes from the learner, before it goes into a prompt.

Two tools:
- ``untrusted``: neutralises the characters a text could use to break out of the place the prompt keeps for it
  (the ``<tags>`` and ``\"\"\"`` blocks the prompts use as delimiters) and drops control characters.
- ``injection_signals``: spots the usual ways of trying to give the model new orders ("ignore your
  instructions", "show me your system prompt", "you are now DAN"...), in English and Spanish.

Detection is a heuristic: it only RECORDS a signal (and refuses a scene description, where an order has no place).
The real defence is in the prompts: what the learner writes always goes inside delimiters, and the prompt says
that it is content to answer or to analyse, never instructions.
"""

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t]+")

# Each pattern is one family of attempts; its name is what gets recorded (never the text itself).
_PATTERNS: dict[str, re.Pattern[str]] = {
    "override": re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|above|prior|earlier|all|your|the|these)\b"
        r".{0,25}\b(instructions?|rules?|prompts?|guidelines|directions)\b"
        r"|\b(ignora|olvida|omite|salta(te)?|desobedece)\b.{0,40}\b(instrucciones|reglas|indicaciones|prompt)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "reveal": re.compile(
        r"\b(reveal|show|print|repeat|tell me|give me|what (is|are))\b.{0,30}\b(system prompt|your (instructions|prompt|rules)"
        r"|(initial|hidden|secret) (instructions|prompt))\b"
        r"|\b(muestra|revela|dime|repite|imprime|cu[aá]les son)\b.{0,30}\b(tus instrucciones|tu prompt|tus reglas"
        r"|el prompt|prompt del sistema)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "role_hijack": re.compile(
        r"\b(you are now|from now on you are|act as|pretend to be)\b.{0,40}\b(dan|jailbreak|unrestricted|unfiltered"
        r"|developer mode|no (rules|limits|restrictions)|evil|an? (ai|assistant) without)\b"
        r"|\b(developer mode|jailbreak|do anything now)\b"
        r"|\b(ahora eres|act[uú]a como|finge ser)\b.{0,40}\b(sin (reglas|l[ií]mites|restricciones|filtros)|modo desarrollador)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "fake_turn": re.compile(
        r"(^|\n)\s*(system|assistant|developer)\s*:|<\s*/?\s*(system|instructions?|scene|part|learner_message)\s*>"
        r"|\[/?(inst|system)\]|<\|im_(start|end)\|>",
        re.IGNORECASE,
    ),
}


def untrusted(text: str | None, *, max_chars: int | None = None) -> str:
    """The text, safe to place inside a delimited block of a prompt."""
    if not text:
        return ""
    clean = unicodedata.normalize("NFKC", text)
    clean = _CONTROL.sub(" ", clean)
    # Angle brackets and triple quotes are the delimiters of our prompts: the learner never needs them.
    clean = clean.replace("<", "‹").replace(">", "›").replace('"""', "''")
    clean = _SPACES.sub(" ", clean).strip()
    if max_chars is not None and len(clean) > max_chars:
        clean = clean[:max_chars].rstrip()
    return clean


def injection_signals(text: str | None) -> list[str]:
    """Names of the attempt families found in the text (empty when it looks normal)."""
    if not text:
        return []
    normalised = unicodedata.normalize("NFKC", text)
    return [name for name, pattern in _PATTERNS.items() if pattern.search(normalised)]
