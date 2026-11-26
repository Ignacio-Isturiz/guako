// Aviso de documentos nuevos: si los Términos o la Política cambiaron desde que la persona los aceptó,
// se lo pedimos al entrar a la app (Ley 1581: la autorización es previa y expresa). Sin aceptarlos, el
// backend no deja usar la IA (403 terms_required), así que no se insiste más de una vez por visita.
import { t } from '@/core/i18n.js'
import { getSession } from '@/features/auth/index.js'
import { openLegal } from '@/features/legal/index.js'
import { loadConsents, termsUpToDate, acceptTerms } from '@/features/app/data/consent.js'
import { confirmDialog } from '@/features/app/components/confirm-dialog/confirm-dialog.js'
import { toast } from '@/features/app/components/toast/toast.js'
import { errorText } from '@/features/app/data/sessions-api.js'

let askedFor = null // correo de la cuenta a la que ya se le preguntó en esta visita

export async function checkTerms() {
  const email = getSession()?.email
  if (!email || askedFor === email) return
  askedFor = email
  if (!(await loadConsents()) || termsUpToDate()) return

  const accept = await confirmDialog({
    title: t('app.consent.termsTitle'),
    text: t('app.consent.termsText'),
    yes: t('app.consent.termsAccept'),
    no: t('app.consent.termsRead'),
  })
  if (!accept) {
    openLegal('privacy')
    askedFor = null // al volver a navegar se le pregunta de nuevo
    return
  }
  try {
    await acceptTerms()
    toast(t('app.consent.termsDone'))
  } catch (err) {
    askedFor = null
    toast(errorText(err))
  }
}
