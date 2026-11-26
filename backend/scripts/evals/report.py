"""The consolidated report: the latest run of every set plus the human review, in one dated Markdown file.

For every set it always states: when it ran, who answered (provider:model), the prompt version, the estimated and
the actual cost, how many cases failed and why. A set that has never run, or whose run measured nothing, is listed
as NOT MEASURED with the reason, never left blank and never given a number.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.evals import grammar, judges, pronunciation, rag, review, wer
from scripts.evals.common import RESULTS_DIR, latest_result

SETS = {"grammar": grammar, "judges": judges, "pronunciation": pronunciation, "rag": rag, "wer": wer}
TITLES = {
    "grammar": "Gramática (precisión y recall)",
    "judges": "Jueces: darse a entender y listening",
    "pronunciation": "Pronunciación (Azure)",
    "rag": "Personalización: reglas recuperadas (RAG)",
    "wer": "Reconocimiento de voz (WER)",
}


def _section(name: str, result: dict[str, Any] | None) -> list[str]:
    lines = [f"## {TITLES[name]}", ""]
    if result is None:
        return [*lines, f"**NO MEDIDO**: no hay ninguna corrida. Correr `python -m scripts.run_evals {name} --yes`.", ""]
    served = ", ".join(f"{k} ({v})" for k, v in (result.get("served_by") or {}).items()) or "nadie (ninguna llamada respondió)"
    reasons = ", ".join(f"{k}: {v}" for k, v in result["failure_reasons"].items()) or "ninguno"
    lines += [
        f"- Corrida: `{result['run_id']}` ({result['started_at']} a {result['finished_at']}, UTC)",
        f"- Atendió: {served}",
        f"- Versión del prompt: {result.get('prompt_version') if result.get('prompt_version') is not None else 'no aplica'}",
        f"- Costo estimado antes de correr: ${result['estimated_cost_usd']:.4f}; costo real (estimado por el router): ${result.get('actual_cost_usd', 0.0):.4f}",
        f"- Casos: {result['cases']}; fallidos: {result['failed']} (motivos: {reasons})",
    ]
    if result.get("provider_attempts"):
        lines.append("- Intentos por proveedor: " + ", ".join(f"{k} {v}" for k, v in sorted(result["provider_attempts"].items())))
    lines += ["", "```", *SETS[name].describe(result), "```", ""]
    return lines


def build(results_dir: Path = RESULTS_DIR, reviews: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    latest = {name: latest_result(name, results_dir) for name in SETS}
    review_summary = review.summarize(review.load_reviews() if reviews is None else reviews)
    total_cost = sum((r or {}).get("actual_cost_usd", 0.0) for r in latest.values())
    lines = [
        f"# Evals de Guako: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        f"Costo real de las corridas incluidas: **${total_cost:.4f}** (estimación del router con los precios de la configuración, no la factura).",
        "",
    ]
    for name in SETS:
        lines += _section(name, latest[name])
    lines += ["## Revisión humana", "", "```", *review.describe(review_summary), "```", ""]
    data = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "total_cost_usd": round(total_cost, 6),
            "sets": {k: (None if v is None else {key: val for key, val in v.items() if key != "rows"}) for k, v in latest.items()},
            "human_review": review_summary}  # fmt: skip
    return "\n".join(lines), data


def write(results_dir: Path = RESULTS_DIR) -> Path:
    text, data = build(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    path = results_dir / f"report-{stamp}.md"
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
