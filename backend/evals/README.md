# Evals

Casos de prueba con respuesta esperada conocida, para medir la calidad del tutor. Todo se corre con **un solo comando**, `python -m scripts.run_evals`, desde `backend/`. El código está en `scripts/evals/`.

| Conjunto | Datos | Qué mide | Quién responde |
|---|---|---|---|
| `grammar` | `grammar/cases.jsonl` (40 frases: 34 con errores, 6 correctas) | precisión, recall, corrección, falsos positivos; 3 repeticiones | router de la app, uso "analysis" (OpenAI primero, después Groq y Gemini) |
| `judges` | `judges/cases.jsonl` (15 casos) | coincidencia del juez con una persona en "darse a entender" y "listening" | router, uso "analysis" |
| `pronunciation` | `grammar/pronunciation_cases.jsonl` + `grammar/audio/` (8 audios) | si las palabras mal pronunciadas a propósito salen como "palabras que costaron" | Azure Speech (sin router ni respaldo) |
| `rag` | `rag/cases.jsonl`, `rag/cases_fragments.jsonl` | personalización: si se adjunta la regla gramatical correcta (precisión, cobertura, regla falsa) y el barrido de umbrales | embeddings de Gemini + PostgreSQL |
| `wer` | `audio/latency/*.ogg` + `manifest.csv` (20 audios) | WER del reconocimiento de voz, global, por audio, por condición, por acento y por hablante | router de STT (Groq Whisper, respaldo OpenAI) |

Los **ejercicios personalizados no tienen eval** todavía; el reporte lo dice.

## Cómo correrlo

```powershell
python -m scripts.run_evals grammar             # muestra qué enviaría y cuánto costaría; NO envía nada
python -m scripts.run_evals grammar --yes       # lo corre (3 repeticiones)
python -m scripts.run_evals grammar --yes --limit 3 --repeats 1   # prueba barata
python -m scripts.run_evals judges --yes
python -m scripts.run_evals pronunciation --yes # gasta segundos de la cuota gratis de Azure (5 h/mes)
python -m scripts.run_evals rag --yes           # necesita PostgreSQL con las reglas indexadas
python -m scripts.run_evals wer --yes
python -m scripts.run_evals all --yes           # todos los conjuntos y al final el reporte
python -m scripts.run_evals report              # reporte consolidado de las últimas corridas
```

`rag` y `review` leen la base de datos de `DATABASE_URL`. El `.env` apunta al host `db`, que es el nombre del servicio dentro de docker.

**En esta máquina, `localhost:5432` no es el Postgres de docker.** Ese puerto lo ocupa un PostgreSQL instalado en Windows, que es otra base. Por eso `rag` y `review` se corren dentro de la red de docker, con la imagen de la API. Los volúmenes montan el código actual; `jiwer` se instala solo en ese contenedor temporal. Desde la raíz del repo:

```powershell
docker run --rm -it --network guako_default --env-file backend/.env -e DATABASE_URL="postgresql+asyncpg://guako:<password>@db:5432/guako" -v "${PWD}/backend/app:/app/app:ro" -v "${PWD}/backend/scripts:/app/scripts" -v "${PWD}/backend/evals:/app/evals" -v "${PWD}/backend/results:/app/results" -u root guako-api sh -c "pip install -q jiwer==4.0.0; python -m scripts.run_evals review"
```

Para RAG se cambia `review` por `rag --yes`. `-e DATABASE_URL` hace falta porque `--env-file` de docker no expande `${POSTGRES_USER}`; compose sí lo hace. Si el Postgres de Windows se detiene o el de docker se publica en otro puerto, basta con `$env:DATABASE_URL` apuntando a `localhost` y el comando normal.

## Costo

Las evals usan el router de proveedores de la app, que cae a OpenAI cuando Groq o Gemini se agotan. Para "analysis" la app usa **OpenAI primero**, así que ahí lo normal es pagar. Por eso:

1. **Sin `--yes` no se envía nada.** El comando muestra las llamadas y el costo estimado, suponiendo que OpenAI responde todas (el peor caso).
2. **Si la estimación pasa de `--max-cost`, que por defecto es 2 USD, la corrida no empieza.** Para aceptar un costo mayor hay que subir `--max-cost` a propósito.
3. **La corrida tiene su propio tope de gasto igual a `--max-cost`.** Al llegar a él, el router deja de usar OpenAI, así que una estimación equivocada no se convierte en una factura sin límite.

`--llm-order groq,gemini,openai` cambia el orden solo para esa corrida, por ejemplo para medir con los modelos gratis primero. El costo real lo calcula el router con los precios de la configuración (`PRICE_OPENAI_*`); es una estimación, no la factura.

## Qué guarda cada corrida

`results/evals/<conjunto>-<run_id>.json` (el `run_id` empieza con la fecha y hora UTC):

- `started_at` y `finished_at`;
- `served_by`: qué `proveedor:modelo` respondió y cuántas veces;
- `provider_attempts`: cada intento por proveedor y su resultado, con los 429 y 503 incluidos;
- `prompt_version`, `estimated_cost_usd` y `actual_cost_usd`;
- `cases`, `failed` y `failure_reasons`;
- las métricas y cada caso (`rows`), también los fallidos.

**Fallos.** Si una llamada falla por algo pasajero, el caso se reintenta hasta 3 veces, con esperas de 10, 30 y 60 s o lo que pida el proveedor, hasta 120 s. Cuentan como pasajeros: todos los proveedores sin cuota o saturados (`exhausted`), una respuesta inválida del modelo (`bad_output`), un timeout y un error del proveedor. Un caso que no se completa queda como **fallido con su motivo**; nunca se omite. Las métricas dicen cuántos casos cubren. Una clave mala (`auth`) o un audio inválido no se reintentan.

## Gramática: cómo se cuenta un acierto

Cada frase pasa por `analyze_grammar`, igual que un turno real: el prompt de gramática v2, el router y el filtro de confianza (`MIN_CONFIDENCE`). Un error esperado y uno marcado **coinciden** cuando señalan el mismo lugar: en minúsculas y sin puntuación, un fragmento contiene al otro. Cada error marcado puede coincidir con un solo error esperado.

- **Precisión**: errores marcados que coinciden con uno real, dividido entre todos los errores marcados (las 6 frases correctas incluidas).
- **Recall**: errores reales que se detectaron, dividido entre todos los errores reales.

Estas cifras principales cuentan **el lugar del error**. La corrección se mide aparte, con `fix_accuracy` y con la variante `strict_*`, donde también tiene que coincidir el arreglo. El motivo: una corrección puede ser válida y distinta de la escrita en el caso ("doesn't" o "does not"). Exigirla contaría ese caso a la vez como error no detectado y como falso positivo, y eso hundiría las dos métricas sin que el modelo se haya equivocado.

**Falsos positivos.** Se reportan aparte sobre las 6 frases correctas: cuántas recibieron al menos un error inventado y cuántos errores en total.

**Varianza.** El conjunto se corre 3 veces y se reporta la **mediana y el rango** (mínimo y máximo) de cada métrica.

## WER: normalización

El WER se calcula con `jiwer`, sumando todas las palabras (no es el promedio de los audios). Antes de comparar, la referencia y la transcripción pasan por la misma función, `scripts/evals/wer.py:normalize`:

| Qué | Regla | Ejemplo |
|---|---|---|
| Tildes | se quitan | "Medellín" = "Medellin" |
| Mayúsculas y puntuación | todo a minúsculas; se quita la puntuación; guiones y barras separan palabras | "eight-thirty" = "eight thirty" |
| Contracciones | se expanden | "don't" = "do not", "I'm" = "I am", "can't" = "can not" |
| Números | se pasan a palabras: enteros hasta 9999 y horas | "3" = "three", "8:30" = "eight thirty", "9:00" = "nine" |
| Muletillas | "um", "uh", "er", etc. se quitan | |

Detalles y límites de estas reglas:

- **Contracciones:**
  - `'d` pasa a "would", aunque también puede ser "had". Es el único caso ambiguo.
  - `'s` pasa a "is" solo después de it, he, she, that, what, there, here, who, where y how. En los demás casos es posesivo y solo pierde el apóstrofo.
- **Números:** no se convierten ordinales, decimales ni montos de dinero. Las referencias actuales no tienen ninguno.
- **Lo que no se normaliza**, y por lo tanto cuenta como error:
  - la ortografía británica frente a la estadounidense;
  - las palabras compuestas escritas aparte ("someday" o "some day").

El reporte incluye también el WER **sin normalizar**, para ver cuánto cambian las reglas el resultado.

**Hablantes.** `manifest.csv` tiene las columnas `speaker` y `accent`, y el WER sale también por acento y por hablante. Hoy los 20 audios son de **un solo hablante con acento latinoamericano**. Con eso **no se puede** saber si el reconocimiento es injusto con los acentos latinos, y el reporte lo dice. Para medirlo hacen falta grabaciones de varias personas con acentos distintos, y de hablantes nativos como base de comparación. El audio de WhatsApp que está en la carpeta no figura en el manifest, así que se ignora y aparece listado.

## Revisión humana

Los criterios del MVP piden revisar a mano 100 turnos reales y comparar, en cada dimensión, lo que dijo el sistema con el juicio de una persona.

```powershell
python -m scripts.run_evals review             # un turno a la vez
python -m scripts.run_evals review --summary   # solo la coincidencia, sin preguntar nada
```

Cada turno muestra lo que dijo Guako antes, lo que dijo el estudiante y el resultado de cada dimensión ya analizada: gramática, fluidez, pronunciación, darse a entender y listening. Por cada dimensión pregunta si estás de acuerdo:

- `y`: sí, de acuerdo;
- `n`: no; en darse a entender y listening te pide además **tu** puntaje del 1 al 5, y una nota opcional;
- `s`: salta esa dimensión;
- `q`: sale.

Cada respuesta se guarda en el momento en `results/reviews/human_review.jsonl`, así que salir no pierde nada y la siguiente vez sigue donde quedó. El resumen da, por dimensión, cuántas revisaste y el porcentaje de acuerdo. En las dimensiones con puntaje agrega la coincidencia exacta, la coincidencia a ±1 y el sesgo.

## Reporte consolidado

`python -m scripts.run_evals report` escribe `results/evals/report-<fecha>.md` (y un `.json` con lo mismo). Junta la última corrida de cada conjunto y la revisión humana. De cada conjunto dice:

- la fecha;
- quién respondió;
- la versión del prompt;
- el costo estimado y el real;
- cuántos casos fallaron y por qué;
- las métricas.

Un conjunto que nunca se corrió, o que no pudo medir nada, aparece como **NO MEDIDO** con el motivo.

## Tests de los datos

El formato de los casos lo validan `tests/test_evals_dataset.py`, `tests/test_evals_judges.py` y `tests/test_evals_wer.py`. Los tests de las evals simulan los proveedores; nunca llaman a uno real.

## Notas técnicas de Azure

- El REST de audio corto **sí devuelve fonemas** (`Phonemes` por palabra) en la región `brazilsouth`; no hace falta `azure-cognitiveservices-speech`.
- Los fonemas vienen en el alfabeto SAPI de Azure (`th`, `ax`, `dh`...), no en IPA.
- Los audios de pronunciación: M4A de la Grabadora de Windows sirve (se convierte con ffmpeg); lo ideal es WAV PCM 16 kHz mono, menos de 28 s, un solo hablante, sin ruido.

## Latencia de un turno (lo que el usuario espera)

Es aparte de los evals de calidad. `scripts.measure_turn_latency` mide cuánto tarda Guako en responder un mensaje de voz:

- pasa por el endpoint real (`POST /api/sessions/{id}/turns` y la descarga del audio);
- usa el router de proveedores y el prompt del tutor;
- el historial va creciendo dentro de cada sesión.

Usa una base SQLite y un caché de TTS vacíos y temporales; no llama a Azure ni corre el análisis de fondo. No incluye la red entre el navegador y el servidor ni la detección de fin de habla.

```powershell
python -m scripts.measure_turn_latency        # muestra el plan; no envía nada
python -m scripts.measure_turn_latency --yes  # 20 turnos en 4 sesiones + 4 aperturas
```

Gasta cuota real: cada turno es 1 STT, 1 LLM y 1 TTS. Groq Orpheus tiene unos 100 TTS por día; pasado el tope responde OpenAI, que es de pago y tiene otra latencia. Revisa `tts_provider` en el resumen. Guarda `results/latency/turns-<run_id>.jsonl`.
