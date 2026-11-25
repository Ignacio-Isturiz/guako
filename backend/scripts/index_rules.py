"""Embed the grammar-rule corpus into the ``grammar_rules`` table (PostgreSQL + pgvector).

Run it after the migration and whenever a rule file changes; only new or edited rules are embedded::

    python -m scripts.index_rules
"""

import asyncio
import sys

from app.db import async_session_maker
from app.rag import get_embedder
from app.rag.corpus import load_rules
from app.rag.store import sync_index


async def main() -> int:
    embedder = get_embedder()
    if embedder is None:
        print("GEMINI_API_KEY is not set: nothing to embed with.")
        return 1
    rules = load_rules()
    print(f"{len(rules)} rules in the corpus")
    async with async_session_maker() as db:
        print(await sync_index(db, embedder, rules))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
