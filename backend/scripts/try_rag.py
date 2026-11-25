"""Try the grammar-rule retrieval by hand (REAL embedding call, free quota).

Run from backend/ with DATABASE_URL pointing at a PostgreSQL where the corpus is indexed::

    python -m scripts.try_rag                      # interactive: type a mistake and its fix
    python -m scripts.try_rag "I am waiting you" "I am waiting for you"

Interactive input is ``mistake -> fix`` (the explanation is optional: ``mistake -> fix | why``), and an
optional ``[type]`` at the start restricts the search to that error type (e.g. ``[preposition] ...``).
Without a type it searches every rule. It shows the 3 closest rules and whether the app would attach
the best one (similarity >= RAG_MIN_SIMILARITY).
"""

import asyncio
import re
import sys

from app.config import settings
from app.db import async_session_maker
from app.rag import get_embedder
from app.rag.corpus import rules_by_id
from app.rag.retrieve import query_text
from app.rag.store import search


async def show(embedder, original: str, correction: str, explanation: str = "", error_type: str | None = None) -> None:
    error = {"original": original, "correction": correction, "explanation": explanation}
    [vector] = embedder.embed([query_text(error)], "query")
    async with async_session_maker() as db:
        hits = await search(db, vector, error_type, limit=3)
    rules = rules_by_id()
    scope = error_type or "all types"
    print(f"\n  {original!r} -> {correction!r}   (searching: {scope})")
    for i, hit in enumerate(hits):
        rule = rules.get(hit.rule_id)
        mark = "*" if i == 0 and hit.similarity >= settings.rag_min_similarity else " "
        print(f"  {mark} {hit.similarity:.3f}  {hit.rule_id}  {rule.title if rule else ''}")
    if hits and hits[0].similarity >= settings.rag_min_similarity:
        print(f"  -> the app WOULD attach {hits[0].rule_id}")
    else:
        print(f"  -> the app would attach NO rule (best is under {settings.rag_min_similarity})")


async def main(argv: list[str]) -> int:
    embedder = get_embedder()
    if embedder is None:
        print("GEMINI_API_KEY is not set.")
        return 1
    if len(argv) >= 2:
        await show(embedder, argv[0], argv[1], argv[2] if len(argv) > 2 else "")
        return 0
    print("Type: mistake -> fix   (optional: [type] first, | explanation last). Empty line to quit.")
    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break
        if not line:
            break
        error_type = None
        if m := re.match(r"\[(\w+)\]\s*(.*)", line):
            error_type, line = m.group(1), m.group(2)
        body, _, why = line.partition("|")
        original, arrow, correction = body.partition("->")
        if not arrow:
            print("  Use the form: mistake -> fix")
            continue
        try:
            await show(embedder, original.strip(), correction.strip(), why.strip(), error_type)
        except Exception as exc:  # a typo in the type, the quota...: keep the loop alive
            print(f"  error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
