import './practica.css'
import { t } from '@/core/i18n.js'
import { practiceItems, practiceStats, practiceMark } from '@/features/app/data/store.js'
import { speak, canSpeak } from '@/features/app/services/tts.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { explain } from '@/features/app/utils/explain.js'
import { toast } from '@/features/app/components/toast/toast.js'

// 9. Práctica: escuchar y repetir las palabras y frases de los informes
export default {
  head: () => ({ eyebrow: t('app.practice.eyebrow'), title: t('app.practice.title') }),
  render: () => `
    <section class="card pex">
      <div>
        <h2 class="card__title">${t('app.exercises.cardTitle')}</h2>
        <p class="card__sub">${t('app.exercises.cardText')}</p>
      </div>
      <button class="btn btn--primary" type="button" data-nav="/app/ejercicios">${t('app.exercises.cardBtn')}</button>
    </section>
    <div class="practice" id="practice"></div>`,

  init(root, _p, scope) {
    const items = practiceItems()
    const host = root.querySelector('#practice')
    if (!items.length) {
      host.innerHTML = `<div class="card empty"><p>${t('app.practice.empty')}</p>
        <button class="btn btn--primary" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.nav.start')}</button></div>`
      return
    }

    let tab = 'all'
    let selected = ''
    const done = (id) => (practiceStats()[id]?.ok || 0) >= 1
    const visible = () => items.filter((i) => tab === 'all' || (tab === 'words' ? i.type === 'word' : i.type === 'phrase'))

    const nextPending = (from) => {
      const list = visible()
      const start = Math.max(0, list.findIndex((i) => i.id === from))
      for (let k = 1; k <= list.length; k++) {
        const cand = list[(start + k) % list.length]
        if (!done(cand.id)) return cand.id
      }
      return list[(start + 1) % list.length].id
    }

    const paint = () => {
      const list = visible()
      if (!list.find((i) => i.id === selected)) selected = (list.find((i) => !done(i.id)) || list[0]).id
      const cur = items.find((i) => i.id === selected)
      const total = items.length
      const doneN = items.filter((i) => done(i.id)).length
      const stats = practiceStats()[cur.id]

      host.innerHTML = `
        <aside class="card plist">
          <div class="seg" role="group">
            ${['all', 'words', 'phrases'].map((k) => `<button type="button" data-tab="${k}" class="${tab === k ? 'is-on' : ''}">${t(`app.practice.tabs.${k}`)}</button>`).join('')}
          </div>
          <div class="pprogress">
            <div class="meter-bar" aria-hidden="true"><i style="width:${(doneN / total) * 100}%"></i></div>
            <small>${t('app.practice.progress', { done: doneN, total })}</small>
          </div>
          <ul>
            ${list
              .map(
                (i) => `<li><button type="button" class="pitem ${i.id === selected ? 'is-on' : ''}" data-pick="${esc(i.id)}">
                  <span class="pitem__dot ${done(i.id) ? 'is-done' : ''}">${done(i.id) ? icon('check', 14) : ''}</span>
                  <span class="pitem__text">${esc(i.text)}</span>
                  <small>${t(i.type === 'word' ? 'app.practice.word' : 'app.practice.phrase')}</small>
                </button></li>`,
              )
              .join('')}
          </ul>
        </aside>

        <section class="card pcard">
          <span class="chip chip--sm">${t(cur.type === 'word' ? 'app.practice.word' : 'app.practice.phrase')}</span>
          <h2 class="pcard__text ${cur.type === 'phrase' ? 'is-phrase' : ''}">${esc(cur.text)}</h2>
          ${cur.ipa ? `<p class="ipa ipa--lg">${esc(cur.ipa)}</p>` : ''}
          ${cur.tip ? `<p class="pcard__note"><b>${t('app.practice.tip')}:</b> ${explain(cur.tip)}</p>` : ''}
          ${
            cur.said
              ? `<p class="pcard__note"><b>${t('app.practice.said')}:</b> <s>${esc(cur.said)}</s><br /><b>${t('app.practice.why')}:</b> ${explain(cur.why)}</p>`
              : ''
          }
          <div class="pcard__listen">
            <button class="btn btn--navy" type="button" data-say="1">${icon('volume', 20)}${t('app.practice.listen')}</button>
            <button class="btn btn--outline" type="button" data-say="slow">${t('app.practice.slow')}</button>
          </div>
          ${canSpeak ? '' : `<p class="card__sub">${t('app.practice.noSpeech')}</p>`}
          <p class="pcard__hint">${t('app.practice.hint')}</p>
          <div class="pcard__mark">
            <button class="btn btn--ok" type="button" data-mark="ok">${icon('check', 20)}${t('app.practice.good')}</button>
            <button class="btn btn--outline" type="button" data-mark="again">${icon('repeat', 18)}${t('app.practice.again')}</button>
          </div>
          ${stats?.ok >= 1 ? `<p class="pcard__done">${icon('star', 16)}${t('app.practice.mastered')} · ${stats.ok}×</p>` : ''}
        </section>`
    }

    scope.listen(host, 'click', (e) => {
      const tabBtn = e.target.closest('[data-tab]')
      if (tabBtn) {
        tab = tabBtn.dataset.tab
        return paint()
      }
      const pick = e.target.closest('[data-pick]')
      if (pick) {
        selected = pick.dataset.pick
        return paint()
      }
      const say = e.target.closest('[data-say]')
      if (say) {
        const cur = items.find((i) => i.id === selected)
        if (!canSpeak) toast(t('app.practice.noSpeech'))
        else speak(cur.text, { force: true, rate: say.dataset.say === 'slow' ? 0.6 : 0.95 })
        return
      }
      const mark = e.target.closest('[data-mark]')
      if (mark) {
        practiceMark(selected, mark.dataset.mark === 'ok')
        if (mark.dataset.mark === 'ok') selected = nextPending(selected)
        paint()
      }
    })
    paint()
  },
}
