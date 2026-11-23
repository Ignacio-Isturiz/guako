from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, version: int, **variables: str) -> str:
    """Load ``<name>_v<version>.txt`` and substitute ``{placeholders}``.

    Uses plain replacement instead of ``str.format`` so literal JSON braces in
    the template do not need escaping.
    """
    path = _PROMPTS_DIR / f"{name}_v{version}.txt"
    text = path.read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace("{" + key + "}", value)
    return text
