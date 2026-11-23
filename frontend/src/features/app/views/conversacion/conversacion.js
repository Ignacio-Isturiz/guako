import './conversacion.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { TEMPLATES, TOPICS } from '@/features/app/data/seed.js'
import { createConversation, settings, setSetting } from '@/features/app/data/store.js'
import { speak, stopSpeaking } from '@/features/app/services/tts.js'
import { confirmDialog } from '@/features/app/components/confirm-dialog/confirm-dialog.js'
import { readSetup, clearSetup } from '@/features/app/data/setup.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { toast } from '@/features/app/components/toast/toast.js'
import { registerActivity } from '@/features/app/data/streak.js'
import { explain, gloss } from '@/features/app/utils/explain.js'

// El icono que acompaña a cada expresión de Guako
const MOOD = { idle: 'mic', listening: 'ear', thinking: 'bulb', speaking: 'volume', correcting: 'pencil', celebrating: 'star' }
const MIN_HOLD = 450 // ms mínimos manteniendo la barra para que cuente como "hablé"

const topicText = (s) => (s.topicId === 'custom' ? s.custom.trim() : t(`app.topics.${s.topicId}.name`))

// 4. Conversación: se habla manteniendo presionada la barra espaciadora
export default {
  head: () => ({ eyebrow: '', title: t('app.talk.end') }),
  render() {
    const s = readSetup()
    if (!s || !s.topicId) return ''
    return `
    <section class="talk" id="talk" data-state="idle">
      <header class="talk__top">
        <button class="talk__exit" type="button" id="exitBtn">${icon('back', 20)}<span>${t('app.talk.exit')}</span></button>
        <div class="talk__chips">
          <span class="chip chip--glass">${esc(topicText(s))}</span>
          <span class="chip chip--glass">${esc(s.level)}</span>
          <span class="chip chip--glass" title="${t('app.talk.timer')}">${icon('clock', 16)}<span id="timer">0:00</span></span>
        </div>
        <button class="talk__sound" type="button" id="soundBtn"></button>
      </header>

      <div class="talk__body">
        <div class="talk__stage">
          <div class="avatar">
            <div class="avatar__waves" aria-hidden="true"><i></i><i></i><i></i></div>
            <img class="avatar__mascot" src="${logo}" alt="Guako" width="190" height="190" />
            <span class="avatar__mood" id="mood" aria-hidden="true"></span>
            <div class="confetti" id="confetti" aria-hidden="true"></div>
          </div>
          <p class="talk__state" id="stateLabel" aria-live="polite"></p>
          <div class="talk__line" id="line" aria-live="polite"></div>
          <div class="talk__fix" id="fix" hidden></div>
        </div>
        <aside class="talk__log" aria-label="${t('app.review.title')}">
          <ol id="log"></ol>
          <p class="talk__demo">${icon('shield', 14)}<span>${t('app.talk.demo')}</span></p>
        </aside>
      </div>

      <footer class="talk__bottom">
        <button class="btn btn--glass" type="button" id="repeatBtn">${icon('repeat', 18)}${t('app.talk.repeat')}</button>
        <button class="talk__key" type="button" id="keyBtn" aria-label="${t('app.talk.hold')}">
          <span class="key">SPACE</span><span id="keyText">${t('app.talk.hold')}</span>
        </button>
        <button class="btn btn--glass" type="button" id="endBtn">${icon('stop', 18)}${t('app.talk.end')}</button>
      </footer>

      <div class="talk__finishing" id="finishing" hidden><span>${icon('spinner', 28)}</span><strong>${t('app.talk.finishing')}</strong></div>
    </section>`
  },

  init(root, _p, scope) {
    const setup = readSetup()
    if (!setup || !setup.topicId) {
      toast(t('app.talk.noTopic'))
      navigate('/app/preparar', { replace: true })
      return
    }
    const tpl = setup.topicId === 'custom' ? 'daily' : TOPICS.find((x) => x.id === setup.topicId).template
    const turns = TEMPLATES[tpl].turns // Guako, tú, Guako, tú, ...

    const $ = (id) => root.querySelector(id)
    const talk = $('#talk')
    const label = $('#stateLabel')
    const mood = $('#mood')
    const line = $('#line')
    const fix = $('#fix')
    const log = $('#log')
    const keyBtn = $('#keyBtn')
    const keyText = $('#keyText')
    const touch = matchMedia('(hover: none)').matches
    const wait = (ms) => new Promise((r) => scope.after(r, ms))

    let state = 'idle'
    let busy = true
    let finished = false
    let pos = 0
    let userTurns = 0
    let lastGuako = ''
    let heldAt = 0

    const setState = (s) => {
      state = s
      talk.dataset.state = s
      label.textContent = t(`app.talk.states.${s}`)
      mood.innerHTML = icon(MOOD[s], 22)
    }
    const setKey = (down = false) => {
      keyBtn.classList.toggle('is-down', down)
      keyBtn.disabled = busy && !down
      keyText.textContent = down ? t('app.talk.releasing') : touch ? t('app.talk.holdTouch') : t('app.talk.hold')
    }
    const addLog = (who, turn) => {
      const li = document.createElement('li')
      li.className = `tbubble tbubble--${who}`
      li.innerHTML = `<small>${who === 'guako' ? t('app.talk.guako') : t('app.talk.you')}</small><p>${esc(turn.text)}</p>`
      log.appendChild(li)
      log.scrollTop = log.scrollHeight
    }
    const showLine = (turn) => {
      line.innerHTML = `<p class="talk__en">${esc(turn.text)}</p><p class="talk__gloss">${gloss(turn.gloss)}</p>`
    }
    const confetti = () => {
      const box = $('#confetti')
      const colors = ['#ffc700', '#e8201a', '#0a7cff', '#fff6e0', '#1aa05a']
      box.innerHTML = Array.from({ length: 18 }, (_, i) => {
        const c = colors[i % colors.length]
        return `<i style="left:${10 + ((i * 53) % 80)}%;background:${c};animation-delay:${(i % 6) * 0.08}s;--r:${(i * 47) % 360}deg"></i>`
      }).join('')
      scope.after(() => (box.innerHTML = ''), 2000)
    }

    const guakoSay = async (turn) => {
      setState('speaking')
      showLine(turn)
      addLog('guako', turn)
      lastGuako = turn.text
      await speak(turn.text)
      if (!finished) setState('idle')
    }

    // Después de que el usuario suelta la barra: Guako "piensa", responde y sigue
    const processUser = async () => {
      busy = true
      setKey()
      setState('thinking')
      await wait(1300)
      const u = turns[pos]
      userTurns++
      addLog('user', u)
      pos++
      if (u.notes.length) {
        const n = u.notes[0]
        setState('correcting')
        fix.hidden = false
        fix.innerHTML = `<strong>${t('app.talk.better')}</strong> <s>${esc(n.frag)}</s> → <b>${esc(n.better)}</b><span>${explain(n.why)}</span>`
        await wait(3000)
        fix.hidden = true
      } else {
        setState('celebrating')
        confetti()
        await wait(1500)
      }
      if (pos < turns.length) {
        await guakoSay(turns[pos])
        pos++
        if (pos >= turns.length) {
          // última frase de Guako: despedida y cierre
          setState('celebrating')
          confetti()
          await wait(2400)
          return finish()
        }
      }
      busy = false
      setKey()
    }

    const start = () => {
      if (busy || finished || state === 'listening') return
      heldAt = Date.now()
      setState('listening')
      setKey(true)
    }
    const release = () => {
      if (state !== 'listening') return
      setKey(false)
      if (Date.now() - heldAt < MIN_HOLD) {
        setState('idle')
        toast(t('app.talk.tooShort'))
        return
      }
      processUser()
    }

    const finish = async () => {
      if (finished) return
      finished = true
      stopSpeaking()
      if (userTurns === 0) {
        clearSetup()
        return navigate('/app/inicio')
      }
      $('#finishing').hidden = false
      await wait(900)
      const id = createConversation({
        templateId: tpl,
        topicId: setup.topicId,
        topicLabel: setup.topicId === 'custom' ? setup.custom.trim() : '',
        level: setup.level,
        turns: userTurns,
      })
      clearSetup()
      // Terminar una conversación es la acción clave del día: suma a la racha
      const s = await registerActivity()
      navigate(`/app/informe/${id}`)
      if (s.recoveredToday) toast(t('app.home.streakSaved', { n: s.recoveriesLeft }))
    }

    const askEnd = async () => {
      const ok = await confirmDialog({
        title: t('app.talk.endTitle'),
        text: t('app.talk.endText'),
        yes: t('app.talk.endYes'),
        no: t('app.talk.endNo'),
      })
      if (ok) finish()
    }

    // Teclado: barra espaciadora (se ignora si hay un diálogo abierto)
    const modalOpen = () => document.documentElement.classList.contains('is-locked')
    scope.listen(window, 'keydown', (e) => {
      if (e.code !== 'Space' || modalOpen()) return
      e.preventDefault()
      if (!e.repeat) start()
    })
    scope.listen(window, 'keyup', (e) => {
      if (e.code !== 'Space' || modalOpen()) return
      e.preventDefault() // evita que la barra "pulse" un botón con el foco al soltarla
      release()
    })
    scope.listen(window, 'blur', () => {
      if (state === 'listening') {
        setKey(false)
        setState('idle')
      }
    })
    // Ratón / pantalla táctil: mantener presionado el botón
    scope.listen(keyBtn, 'pointerdown', (e) => {
      e.preventDefault()
      keyBtn.setPointerCapture?.(e.pointerId)
      start()
    })
    scope.listen(keyBtn, 'pointerup', release)
    scope.listen(keyBtn, 'pointercancel', release)

    scope.listen($('#repeatBtn'), 'click', async () => {
      if (busy || !lastGuako) return
      busy = true
      setKey()
      setState('speaking')
      await speak(lastGuako, { rate: 0.85 })
      setState('idle')
      busy = false
      setKey()
    })
    scope.listen($('#endBtn'), 'click', askEnd)
    scope.listen($('#exitBtn'), 'click', askEnd)

    const sound = $('#soundBtn')
    const paintSound = () => {
      const on = settings().sound
      sound.innerHTML = icon(on ? 'volume' : 'mute', 22)
      sound.setAttribute('aria-label', on ? t('app.talk.soundOn') : t('app.talk.soundOff'))
      sound.setAttribute('aria-pressed', String(on))
    }
    scope.listen(sound, 'click', () => {
      setSetting('sound', !settings().sound)
      if (!settings().sound) stopSpeaking()
      paintSound()
      toast(settings().sound ? t('app.talk.soundOn') : t('app.talk.soundOff'))
    })
    paintSound()

    // Cronómetro
    const t0 = Date.now()
    const timer = $('#timer')
    scope.every(() => {
      const s = Math.floor((Date.now() - t0) / 1000)
      timer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
    }, 1000)

    // Empieza Guako
    ;(async () => {
      setState('idle')
      setKey()
      await wait(600)
      await guakoSay(turns[0])
      pos = 1
      busy = false
      setKey()
    })()
  },
}
