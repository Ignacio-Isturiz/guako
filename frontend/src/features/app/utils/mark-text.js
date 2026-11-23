import { esc } from '@/features/app/utils/html.js'

// Marca en el texto del usuario cada fragmento con error (numerado).
// `fragments` es la lista de textos incorrectos, en el orden en que se numeran.
export function markText(text, fragments) {
  const ranges = []
  fragments.forEach((frag, i) => {
    const at = frag ? text.indexOf(frag) : -1
    if (at >= 0) ranges.push({ at, len: frag.length, i })
  })
  ranges.sort((a, b) => a.at - b.at)
  let out = ''
  let cur = 0
  for (const r of ranges) {
    if (r.at < cur) continue
    out += `${esc(text.slice(cur, r.at))}<mark class="err">${esc(text.slice(r.at, r.at + r.len))}<sup>${r.i + 1}</sup></mark>`
    cur = r.at + r.len
  }
  return out + esc(text.slice(cur))
}
