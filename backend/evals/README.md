# Evals

Casos de prueba con respuesta esperada conocida, para medir la calidad del tutor.

- `grammar/cases.jsonl`: 40 frases en inglés. 34 con errores de gramática conocidos (`expected_errors`: fragmento `original`, `correction` y `error_type`) y 6 correctas (lista vacía, para detectar falsos positivos).
- `grammar/pronunciation_cases.jsonl`: 8 frases para pronunciación. Indican las palabras objetivo y el error típico (`mispronunciation`). `audio_file` es `null` hasta grabar cada audio.
- `audio/latency/`: audios para `scripts.measure_latency`.

Cada línea es un JSON. El formato lo valida `tests/test_evals_dataset.py`.

## Correr los evals de gramática

Hace llamadas reales al LLM configurado (consume cuota gratuita). Desde `backend/`:

```powershell
python -m scripts.run_grammar_evals            # los 40 casos
python -m scripts.run_grammar_evals --limit 3  # prueba barata
```

Guarda `results/evals/<run_id>.jsonl` y resume: **recall** (errores esperados que el LLM detectó), **fix_accuracy** (detectados con la misma corrección), **false_positive_rate** (frases correctas donde inventó errores) y errores extra. Un error cuenta como detectado si el fragmento señalado contiene o está contenido en el esperado.
