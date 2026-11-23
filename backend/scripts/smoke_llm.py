"""Manual smoke test: makes a REAL call to the configured provider.

Run from backend/:  python -m scripts.smoke_llm
Never run by pytest. Prints only the parsed result, never keys.
"""

from app.config import settings
from app.llm.factory import get_llm_provider
from app.llm.schemas import GrammarAnalysis
from app.prompts import load_prompt


def main() -> None:
    provider = get_llm_provider(settings)
    prompt = load_prompt("grammar_analysis", 1, text="Yesterday I go to the school and see she friends.")
    result = provider.generate(prompt, GrammarAnalysis)
    print(f"provider={settings.llm_provider} errors_found={len(result.errors)}")
    for err in result.errors:
        print(f"- {err.original!r} -> {err.correction!r} ({err.error_type})")


if __name__ == "__main__":
    main()
