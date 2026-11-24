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

## Evals de pronunciación (Azure Speech)

Hace llamadas reales a Azure y gasta la cuota gratuita (5 h/mes, no se recupera). Por eso el script **no envía nada** a menos que le pases `--yes`:

```powershell
python -m scripts.run_pronunciation_evals        # solo lista qué audios hay y cuáles faltan
python -m scripts.run_pronunciation_evals --yes  # envía los audios (unos 40 s en total)
```

Cada audio va junto a su frase `text`, que es la referencia. El caso cuenta como acierto si **todas** las `target_words` salen por debajo del umbral de "palabra que costó" del informe (`HARD_WORD_THRESHOLD`, hoy 85). Los casos sin audio se informan como `no_audio`; nunca se inventan resultados. Los segundos enviados aquí **no** suman al contador mensual de la app: gastan el margen de seguridad.

Audios por grabar: `backend/evals/grammar/audio/pr_01.m4a` … `pr_08.m4a` (el `pr_01` ya existe). Lee la frase de `text` pronunciando a propósito el error de `mispronunciation`. Formato: M4A de la Grabadora de Windows sirve (el script lo convierte con ffmpeg); lo ideal es WAV PCM 16 kHz mono. Menos de 28 s cada uno (en la práctica 3-6 s), un solo hablante, sin ruido de fondo. Opcional, para medir falsos positivos: una segunda toma leída bien de cada frase como `pr_0X_ok.m4a`.

## Notas técnicas de Azure

- El REST de audio corto **sí devuelve fonemas** (`Phonemes` por palabra) en la región `brazilsouth`; no hace falta `azure-cognitiveservices-speech`.
- Los fonemas vienen en el alfabeto SAPI de Azure (`th`, `ax`, `dh`...), no en IPA.
- Corrección pendiente en la documentación del proyecto: la ruta real de los casos es `backend/evals/grammar/pronunciation_cases.jsonl`, no `evals/pronunciation/`.
