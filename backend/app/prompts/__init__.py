import re
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@lru_cache
def template_text(name: str, version: int) -> str:
    """The raw template ``<name>_v<version>.txt``, placeholders included."""
    return (_PROMPTS_DIR / f"{name}_v{version}.txt").read_text(encoding="utf-8")


def load_prompt(name: str, version: int, **variables: str) -> str:
    """Load ``<name>_v<version>.txt`` and substitute ``{placeholders}``.

    One pass over the TEMPLATE: a value is never scanned again, so a learner who writes "{role}" in the topic
    cannot pull another variable in. Unknown placeholders (literal JSON braces) are left as they are, so the
    template does not need escaping.
    """
    return _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), m.group(0)), template_text(name, version))
