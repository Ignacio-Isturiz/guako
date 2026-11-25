import './ejercicios.css'
import { t, getLang } from '@/core/i18n.js'
import { getExercises, checkAnswer, checkSpeech } from '@/features/app/data/exercises-api.js'
import { errorText } from '@/features/app/data/sessions-api.js'
import { openMic } from '@/features/app/services/recorder.js'
import { speak, canSpeak } from '@/features/app/services/tts.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'

// Práctica personalizada: una ronda de ejercicios variados (elegir, completar, corregir, hablar) hechos con
// las reglas que más te costaron. El servidor decide qué ejercicios y corrige; aquí solo se pinta y se contesta.
// Lenguaje: "bien" / "todavía no". Nunca se dice que mejoraste: contestar bien un ejercicio no prueba eso.

const ROUND_SIZE = 8
const MAX_RECORD_MS = 12000 // una frase corta; el backend rechaza audios más largos
const MIN_BLOB_BYTES = 1000 // menos que esto es silencio o un toque sin querer
const K = (key, vars) => t(`app.exercises.${key}`, vars)

export default {
  head: () => ({ eyebrow: K('eyebrow'), title: K('title') }),
  render: () => `<div class="ex" id="ex"></div>`,

  init(root, _params, scope) {
    const host = root.querySelector('#ex')
    const rule = new URLSearchParams(location.search).get('rule') || undefined

    // phase: loading | empty | error | run | done
    let phase = 'loading'
    let round = { exercises: [], focus: [] }
    let i = 0
    let results = [] // true/false por ejercicio
    let answer = null // { result } cuando ya se contestó el ejercicio actual
    let busy = false // se está comprobando una respuesta
    let rec = 'idle' // idle | rec | check (ejercicio de hablar)
    let note = '' // aviso bajo el ejercicio (error de red, silencio…)
    let mic = null
    let timer = null
    let alive = true
    scope.onCleanup(() => {
      alive = false
      clearTimeout(timer)
      mic?.cancel()
      mic?.close()
    })

    const current = () => round.exercises[i]

    async function load() {
      phase = 'loading'
      paint()
      try {
        round = await getExercises({ size: ROUND_SIZE, rule })
        if (!alive) return
        phase = round.exercises.length ? 'run' : 'empty'
        i = 0
        results = []
        answer = null
        note = ''
      } catch (err) {
        if (!alive) return
        phase = 'error'
        note = errorText(err)
      }
      paint()
    }

    // ---- pintar ----
    const kindLabel = (kind) => K(`kind.${kind}`)

    const head = () => `
      <div class="ex__head">
        <div class="ex__bar meter-bar" aria-hidden="true"><i style="width:${(i / round.exercises.length) * 100}%"></i></div>
        <small>${K('progress', { n: i + 1, total: round.exercises.length })}</small>
      </div>
      <div class="ex__meta">
        <span class="chip chip--sm">${esc(kindLabel(current().kind))}</span>
        ${current().personal ? `<span class="ex__mine">${icon('star', 14)}${K('mine')}</span>` : ''}
        ${current().rule_title ? `<span class="ex__rulename">${esc(current().rule_title)}</span>` : ''}
      </div>`

    const gapInput = (disabled) =>
      `<input class="ex__gap" type="text" data-input autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="${esc(K('gapLabel'))}" ${disabled ? 'disabled' : ''} />`

    function body(ex) {
      const done = !!answer
      if (ex.kind === 'choice') {
        const picked = answer?.picked
        return `
          <p class="ex__prompt">${esc(ex.prompt)}</p>
          <div class="ex__options" role="group">
            ${ex.options
              .map((o) => {
                const state = !done ? '' : o === answer.result.expected ? 'is-right' : o === picked ? 'is-wrong' : ''
                return `<button type="button" class="ex__option ${state}" data-option="${esc(o)}" ${done || busy ? 'disabled' : ''}>${esc(o)}</button>`
              })
              .join('')}
          </div>`
      }
      if (ex.kind === 'fill') {
        const [before, after = ''] = ex.prompt.split('___')
        return `
          <p class="ex__prompt">${K('fillPrompt')}</p>
          <p class="ex__sentence">${esc(before)}${gapInput(done || busy)}${esc(after)}</p>
          ${done ? '' : `<button type="button" class="btn btn--primary" data-submit ${busy ? 'disabled' : ''}>${K('check')}</button>`}`
      }
      if (ex.kind === 'fix') {
        return `
          <p class="ex__prompt">${K('fixPrompt')}</p>
          <p class="ex__wrong">${esc(ex.prompt)}</p>
          <input class="ex__text" type="text" data-input autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="${esc(K('fixLabel'))}" ${done || busy ? 'disabled' : ''} />
          ${done ? '' : `<button type="button" class="btn btn--primary" data-submit ${busy ? 'disabled' : ''}>${K('check')}</button>`}`
      }
      // speak
      const label = rec === 'rec' ? K('recording') : rec === 'check' ? K('checking') : K('say')
      return `
        <p class="ex__prompt">${K('speakPrompt')}</p>
        <p class="ex__sentence ex__sentence--say">${esc(ex.prompt)}</p>
        ${canSpeak ? `<button type="button" class="btn btn--outline btn--sm" data-listen>${icon('volume', 18)}${K('listen')}</button>` : ''}
        ${
          done && answer.result.correct
            ? ''
            : `<button type="button" class="ex__mic ${rec === 'rec' ? 'is-rec' : ''}" data-mic aria-pressed="${rec === 'rec'}" ${rec === 'check' ? 'disabled' : ''}>${icon('mic', 18)}<span>${label}</span></button>`
        }`
    }

    function feedback(ex) {
      if (!answer) return note ? `<p class="ex__note" role="alert">${esc(note)}</p>` : ''
      const r = answer.result
      const detail =
        ex.kind === 'speak'
          ? `<p>${r.heard ? K('heard', { text: esc(r.heard) }) : K('heardNothing')}</p>${r.correct ? '' : `<p>${K('expectedSay', { text: esc(r.expected) })}</p>`}`
          : r.correct
            ? ''
            : `<p>${K('expected', { text: esc(r.expected) })}</p>`
      const ruleBlock = r.rule
        ? `<details class="ex__rule" ${r.correct ? '' : 'open'}>
            <summary>${t('app.report.live.rule')}: ${esc(r.rule.title)} <span>${esc(r.rule.level)}</span></summary>
            <p>${esc(getLang() === 'es' ? r.rule.rule_es : r.rule.rule)}</p>
          </details>`
        : ''
      const last = i + 1 >= round.exercises.length
      return `
        <div class="ex__result ${r.correct ? 'is-ok' : 'is-no'}" role="status">
          <p class="ex__verdict">${r.correct ? icon('check', 18) : ''}${r.correct ? K('right') : K('notYet')}</p>
          ${detail}
          ${ruleBlock}
        </div>
        <div class="ex__actions">
          ${ex.kind === 'speak' && !r.correct ? `<button type="button" class="btn btn--outline" data-retry>${icon('repeat', 18)}${K('retry')}</button>` : ''}
          <button type="button" class="btn btn--navy" data-next>${last ? K('seeSummary') : K('next')}</button>
        </div>`
    }

    function paintRun() {
      const ex = current()
      host.innerHTML = `
        <section class="card ex__card">
          ${head()}
          <div class="ex__body">${body(ex)}</div>
          ${feedback(ex)}
        </section>`
      if (!answer && (ex.kind === 'fill' || ex.kind === 'fix')) host.querySelector('[data-input]')?.focus()
    }

    function paintDone() {
      const ok = results.filter(Boolean).length
      host.innerHTML = `
        <section class="card ex__card ex__summary">
          <h2 class="card__title">${K('summaryTitle')}</h2>
          <p class="ex__score"><strong>${ok}</strong> ${K('summaryOf', { total: results.length })}</p>
          ${
            round.focus.length
              ? `<p class="card__sub">${K('summaryFocus')}</p>
                 <ul class="ex__focus">${round.focus.map((f) => `<li>${esc(f.title)}${f.count ? ` <small>${K('times', { n: f.count })}</small>` : ''}</li>`).join('')}</ul>`
              : ''
          }
          <div class="ex__actions">
            <button type="button" class="btn btn--primary" data-again>${icon('repeat', 18)}${K('anotherRound')}</button>
            <button type="button" class="btn btn--outline" data-nav="/app/practica">${K('back')}</button>
          </div>
        </section>`
    }

    function paint() {
      if (phase === 'loading') {
        host.innerHTML = `<div class="card empty"><p>${icon('spinner', 24)} ${K('loading')}</p></div>`
      } else if (phase === 'empty') {
        host.innerHTML = `<div class="card empty"><p>${K('empty')}</p>
          <button class="btn btn--primary" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.nav.start')}</button></div>`
      } else if (phase === 'error') {
        host.innerHTML = `<div class="card empty"><p role="alert">${esc(note)}</p>
          <button class="btn btn--primary" type="button" data-reload>${t('app.report.live.retry')}</button></div>`
      } else if (phase === 'done') paintDone()
      else paintRun()
    }

    // ---- contestar ----
    async function submit(value) {
      const ex = current()
      if (busy || answer || !value.trim()) return
      busy = true
      note = ''
      paint()
      try {
        const result = await checkAnswer(ex.id, value)
        if (!alive) return
        answer = { result, picked: value }
        results[i] = result.correct
      } catch (err) {
        if (!alive) return
        note = errorText(err)
      } finally {
        busy = false
        if (alive) paint()
      }
    }

    async function finishRecording() {
      clearTimeout(timer)
      const ex = current()
      const recorded = await mic.stop()
      mic.close() // apaga el micrófono entre intentos
      mic = null
      if (!alive) return
      if (!recorded || recorded.blob.size < MIN_BLOB_BYTES) {
        rec = 'idle'
        note = errorText({ code: 'audio_empty' })
        return paint()
      }
      rec = 'check'
      paint()
      try {
        const result = await checkSpeech(ex.id, recorded.blob, `say.${recorded.ext}`)
        if (!alive) return
        answer = { result }
        if (result.correct) results[i] = true // un intento fallido se puede repetir; cuenta lo último
        else results[i] = false
      } catch (err) {
        if (!alive) return
        note = errorText(err)
      } finally {
        rec = 'idle'
        if (alive) paint()
      }
    }

    async function toggleMic() {
      if (rec === 'check') return
      if (rec === 'rec') return finishRecording()
      try {
        mic = await openMic()
      } catch (err) {
        note = errorText(err)
        return paint()
      }
      if (!alive) return mic.close()
      mic.start()
      rec = 'rec'
      note = ''
      paint()
      timer = setTimeout(finishRecording, MAX_RECORD_MS)
    }

    const next = () => {
      if (i + 1 >= round.exercises.length) phase = 'done'
      else {
        i += 1
        answer = null
        note = ''
      }
      paint()
      window.scrollTo(0, 0)
    }

    scope.listen(host, 'click', (e) => {
      const opt = e.target.closest('[data-option]')
      if (opt) return submit(opt.dataset.option)
      if (e.target.closest('[data-submit]')) return submit(host.querySelector('[data-input]')?.value || '')
      if (e.target.closest('[data-mic]')) return toggleMic()
      if (e.target.closest('[data-listen]')) return speak(current().prompt, { force: true, rate: 0.9 })
      if (e.target.closest('[data-retry]')) {
        answer = null
        note = ''
        return paint()
      }
      if (e.target.closest('[data-next]')) return next()
      if (e.target.closest('[data-again]') || e.target.closest('[data-reload]')) return load()
    })
    scope.listen(host, 'keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('[data-input]')) {
        e.preventDefault()
        submit(e.target.value)
      }
    })

    load()
  },
}
