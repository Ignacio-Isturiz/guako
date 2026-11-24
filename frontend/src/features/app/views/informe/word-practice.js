// Práctica "ahora tú" de las palabras que costaron: la persona dice la palabra, el backend la evalúa y
// decide (lo lograste → la palabra se bloquea; si no, hasta 2 intentos). Las reglas viven en el servidor:
// aquí solo se graba, se envía y se pinta el estado que devuelve.
//
// Lenguaje: "lo lograste" / "todavía cuesta". Nunca se dice que algo está "mal" ni se habla del acento.
import { t } from '@/core/i18n.js'
import { practiceWord, errorText } from '@/features/app/data/sessions-api.js'
import { openMic } from '@/features/app/services/recorder.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'

const MAX_RECORD_MS = 5000 // una palabra dura uno o dos segundos; el backend rechaza audios largos
const MIN_BLOB_BYTES = 1000 // menos que esto es silencio o un toque sin querer
const K = (key, vars) => t(`app.report.live.pron.practice.${key}`, vars)

// Los sonidos de la palabra con su puntaje; el que más costó va resaltado
const soundsHtml = (r) =>
  r?.sounds?.length
    ? `<p class="hard__sounds" aria-label="${esc(t('app.report.live.pron.sounds'))}">${r.sounds
        .map((s, i) => `<span class="hard__sound ${i === r.weakest_sound ? 'is-weak' : ''}">/${esc(s.ipa)}/ <b>${s.score}</b></span>`)
        .join('')}</p>`
    : ''

export function createWordPractice(root, sessionId, scope) {
  const items = new Map() // palabra → { practice, phase: 'idle' | 'rec' | 'check', note }
  let mic = null
  let active = null // palabra que se está grabando o evaluando
  let timer = null
  let alive = true
  scope.onCleanup(() => {
    alive = false
    clearTimeout(timer)
    mic?.cancel()
    mic?.close()
  })

  const view = (word, it) => {
    const p = it.practice
    if (p.passed) return `<p class="practice__msg is-ok">${icon('check', 16)}<span>${K('passed', { score: p.best_score ?? '' })}</span></p>`
    if (p.locked) return `<p class="practice__msg">${K('locked', { score: p.best_score ?? '–' })}</p>`
    const note = it.note
      ? `<p class="practice__msg ${it.note.kind === 'error' ? 'is-err' : ''}">${esc(it.note.text)}</p>${soundsHtml(it.note.result)}`
      : ''
    const label = it.phase === 'rec' ? K('recording') : it.phase === 'check' ? K('checking') : K('start', { word })
    const disabled = it.phase === 'check' || (active && active !== word)
    return `${note}
      <div class="practice__row">
        <button type="button" class="practice__btn ${it.phase === 'rec' ? 'is-rec' : ''}" data-practice="${esc(word)}" aria-pressed="${it.phase === 'rec'}" ${disabled ? 'disabled' : ''}>
          ${icon('mic', 18)}<span>${label}</span>
        </button>
        <small class="practice__left">${K('attempts', { n: p.attempts_left })}</small>
      </div>`
  }

  const paint = (word) => {
    const box = [...root.querySelectorAll('[data-practice-box]')].find((b) => b.dataset.practiceBox === word)
    const it = items.get(word)
    if (!box || !it) return
    box.innerHTML = view(word, it)
    box.closest('.hard__word')?.classList.toggle('is-done', it.practice.passed)
  }
  const paintAll = () => items.forEach((_, word) => paint(word))

  async function finish(word) {
    clearTimeout(timer)
    const it = items.get(word)
    const rec = await mic.stop()
    mic.close() // apaga el micrófono entre intentos (si no, el navegador sigue mostrando "grabando")
    mic = null
    if (!alive) return
    if (!rec || rec.blob.size < MIN_BLOB_BYTES) {
      it.phase = 'idle'
      active = null
      it.note = { kind: 'error', text: errorText({ code: 'audio_empty' }) }
      return paintAll()
    }
    it.phase = 'check'
    paintAll()
    try {
      const r = await practiceWord(sessionId, word, rec.blob, `word.${rec.ext}`)
      if (!alive) return
      it.practice = r.practice
      if (r.status === 'no_speech') it.note = { kind: 'no_speech', text: K('noSpeech') }
      else if (r.status === 'retry') {
        // Si Whisper entendió otra palabra, se dice cuál: es lo más útil para corregirse
        const text = r.heard && !r.heard_ok ? K('retryHeard', { heard: r.heard, n: r.practice.attempts_left }) : K('retry', { score: r.score, n: r.practice.attempts_left })
        it.note = { kind: 'retry', text, result: r }
      }
      else it.note = null
    } catch (err) {
      if (!alive) return
      if (err?.code === 'practice_locked') it.practice = { ...it.practice, locked: true, attempts_left: 0 }
      it.note = { kind: 'error', text: errorText(err) }
    } finally {
      if (alive) {
        it.phase = 'idle'
        active = null
        paintAll()
      }
    }
  }

  return {
    // Pinta el estado de cada palabra (viene en el informe) dentro de su tarjeta
    mount(hardWords) {
      items.clear()
      for (const w of hardWords) items.set(w.word, { practice: w.practice, phase: 'idle', note: null })
      paintAll()
    },

    // Toque en "Ahora tú": empieza a grabar; otro toque (o 5 segundos) termina y evalúa
    async toggle(word) {
      const it = items.get(word)
      if (!it || it.practice.locked || it.phase === 'check' || (active && active !== word)) return
      if (it.phase === 'rec') return finish(word)
      try {
        mic = await openMic()
      } catch (err) {
        it.note = { kind: 'error', text: errorText(err) }
        return paint(word)
      }
      if (!alive) return mic.close()
      mic.start()
      active = word
      it.phase = 'rec'
      it.note = null
      paintAll()
      timer = setTimeout(() => finish(word), MAX_RECORD_MS)
    },
  }
}
