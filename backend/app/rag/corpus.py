"""The grammar-rule corpus: plain-text files in ``rules/``, one per error type, rules separated by ``===``.

The files are the single source of truth. The database only keeps an embedding per rule (and a hash of the
text it came from, so changing a rule re-embeds just that one); what is shown to the learner is always read
from here. The rules are written from scratch (explanations and examples are original) and not copied from
any grammar book or website.

A rule looks like this (``->`` splits the incorrect sentence from the correct one)::

    id: article.a_an
    error_type: article
    level: A1
    title: A or an
    rule: Use "an" before a vowel sound ...
    rule_es: "An" antes de un sonido vocálico ...
    examples:
    - She is a engineer. -> She is an engineer.
    spanish_note: why Spanish speakers make this mistake.
"""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.analysis.grammar import GrammarErrorType

RULES_DIR = Path(__file__).parent / "rules"
SEPARATOR = "==="
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_FIELDS = {"id", "error_type", "level", "title", "rule", "rule_es", "spanish_note"}


class CorpusError(ValueError):
    """A rule file is malformed. Raised at load time so a typo never reaches a learner."""


@dataclass(frozen=True)
class Rule:
    id: str
    error_type: str
    level: str
    title: str
    rule: str
    rule_es: str
    examples: tuple[str, ...]
    spanish_note: str

    def embedding_text(self) -> str:
        """What gets embedded: the title, the rule and the example mistakes (a learner's error looks like these)."""
        wrong = [e.split("->")[0].strip() for e in self.examples]
        return f"{self.title}. {self.rule} Typical mistakes: {' | '.join(wrong)}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.embedding_text().encode()).hexdigest()


def _parse_block(text: str, source: str) -> Rule:
    fields: dict[str, str] = {}
    examples: list[str] = []
    in_examples = False
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        if in_examples and line.startswith("- "):
            examples.append(line[2:].strip())
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or (key != "examples" and key not in _FIELDS):
            raise CorpusError(f"{source}: unexpected line {line[:60]!r}")
        in_examples = key == "examples"
        if not in_examples:
            fields[key] = value.strip()
    missing = _FIELDS - fields.keys()
    if missing:
        raise CorpusError(f"{source}: missing {sorted(missing)} in rule {fields.get('id', '?')}")
    if not examples or any("->" not in e for e in examples):
        raise CorpusError(f"{source}: rule {fields['id']} needs examples written as 'wrong -> right'")
    return Rule(examples=tuple(examples), **fields)


def _validate(rule: Rule, source: str) -> None:
    if rule.error_type not in {t.value for t in GrammarErrorType}:
        raise CorpusError(f"{source}: {rule.id} has unknown error_type {rule.error_type!r}")
    if not rule.id.startswith(f"{rule.error_type}."):
        raise CorpusError(f"{source}: id {rule.id!r} must start with '{rule.error_type}.'")
    if rule.level not in LEVELS:
        raise CorpusError(f"{source}: {rule.id} has unknown level {rule.level!r}")


@lru_cache
def load_rules(directory: Path = RULES_DIR) -> tuple[Rule, ...]:
    rules: list[Rule] = []
    for path in sorted(directory.glob("*.txt")):
        for block in path.read_text(encoding="utf-8").split(f"\n{SEPARATOR}\n"):
            if not block.strip():
                continue
            rule = _parse_block(block, path.name)
            _validate(rule, path.name)
            rules.append(rule)
    ids = [r.id for r in rules]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise CorpusError(f"duplicated rule ids: {duplicated}")
    return tuple(rules)


@lru_cache
def rules_by_id() -> dict[str, Rule]:
    return {r.id: r for r in load_rules()}
