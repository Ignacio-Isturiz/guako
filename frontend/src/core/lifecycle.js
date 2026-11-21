// Registro de "limpiezas": cada componente anota aquí lo que debe deshacerse
// (listeners, temporizadores, observadores) antes de volver a pintar,
// por ejemplo al cambiar de idioma o de pantalla.
//
// `createScope()` crea un ámbito propio (por ejemplo, uno por pantalla de la app);
// las funciones exportadas abajo usan el ámbito global de la landing.
export function createScope() {
  const fns = []
  const scope = {
    onCleanup: (fn) => fns.push(fn),
    run() {
      while (fns.length) {
        try {
          fns.pop()()
        } catch {
          /* una limpieza fallida no debe impedir las demás */
        }
      }
    },
    listen(target, type, handler, opts) {
      target.addEventListener(type, handler, opts)
      scope.onCleanup(() => target.removeEventListener(type, handler, opts))
    },
    every(fn, ms) {
      const id = setInterval(fn, ms)
      scope.onCleanup(() => clearInterval(id))
      return id
    },
    after(fn, ms) {
      const id = setTimeout(fn, ms)
      scope.onCleanup(() => clearTimeout(id))
      return id
    },
  }
  return scope
}

const root = createScope()

export const onCleanup = root.onCleanup
export const runCleanups = root.run
export const listen = root.listen
export const every = root.every
