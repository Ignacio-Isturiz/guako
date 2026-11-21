// Textos legales de Guako (español e inglés).
//
// IMPORTANTE: es un borrador de partida redactado a partir de las prácticas habituales
// y de la normativa colombiana de protección de datos (Ley 1581 de 2012, su reglamentación
// compilada en el Decreto 1074 de 2015 y el Estatuto del Consumidor, Ley 1480 de 2011).
// Debe revisarlo un abogado antes de publicarse y ajustarse a como funcione realmente
// el producto (proveedores, plazos de conservación, medios de pago, etc.).
//
// Los datos de la empresa se cambian aquí, en un solo sitio:
export const LEGAL_CONFIG = {
  company: 'Guako',
  email: 'privacidad@guako.example', // ← reemplazar por el correo real de contacto
  country: { es: 'Colombia', en: 'Colombia' }, // ← país/jurisdicción de la empresa
}

export const LEGAL = {
  /* ====================================================================== */
  es: {
    terms: {
      intro: `Estos Términos y condiciones regulan el uso de {company} (el «Servicio»). Léelos con calma: al crear una cuenta o usar el Servicio aceptas lo que aquí se dice.`,
      sections: [
        {
          h: 'Aceptación de los términos',
          p: [
            `Al registrarte, iniciar sesión o usar {company} declaras que leíste y aceptas estos términos y la Política de privacidad. Si no estás de acuerdo, no uses el Servicio.`,
            `{company} está dirigido a personas mayores de 18 años. Si eres menor de edad, solo puedes usarlo con la autorización y la supervisión de tu madre, padre o representante legal.`,
          ],
        },
        {
          h: 'Qué es Guako',
          p: [
            `{company} es una aplicación para practicar inglés hablado: te ayuda a mejorar tu pronunciación, tu gramática y tu seguridad al hablar mediante conversaciones, roles y temas con un tutor virtual.`,
            `El Servicio es una herramienta de práctica. No es una certificación oficial de nivel de idioma ni garantiza resultados específicos.`,
          ],
        },
        {
          h: 'Tu cuenta',
          ul: [
            `Debes darnos datos verdaderos y mantenerlos actualizados.`,
            `Eres responsable de la confidencialidad de tu contraseña y de los códigos de verificación (OTP) que recibas. No los compartas con nadie.`,
            `Eres responsable de lo que ocurra desde tu cuenta. Si sospechas de un acceso no autorizado, avísanos de inmediato en {email}.`,
            `Cada cuenta es personal: no puedes venderla, cederla ni usarla en nombre de otra persona.`,
          ],
        },
        {
          h: 'Uso aceptable',
          p: [`Al usar el Servicio te comprometes a no:`],
          ul: [
            `Usarlo para fines ilegales o para dañar a otras personas.`,
            `Suplantar a otra persona ni dar información engañosa.`,
            `Intentar vulnerar la seguridad, hacer ingeniería inversa, copiar o extraer de forma masiva el contenido o el código.`,
            `Usar programas automatizados para abusar del Servicio o sobrecargarlo.`,
            `Introducir contenido ofensivo, discriminatorio o ilegal en tus conversaciones de práctica.`,
          ],
        },
        {
          h: 'Tu voz y el contenido que generas',
          p: [
            `Cuando practicas, el Servicio puede procesar tus grabaciones de voz y sus transcripciones para darte retroalimentación. Tú conservas los derechos sobre ese contenido.`,
            `Nos otorgas una licencia limitada, no exclusiva y revocable, solo para tratarlo con el fin de prestarte el Servicio y, únicamente si lo autorizas de forma expresa, para mejorarlo. Cómo tratamos tus datos se explica en la Política de privacidad.`,
          ],
        },
        {
          h: 'Planes, pagos y renovaciones',
          p: [
            `{company} puede ofrecer un plan gratuito y planes de pago. Antes de contratar verás con claridad el precio, el ciclo de facturación (por ejemplo, mensual o anual), si hay periodo de prueba y cuándo empieza el cobro.`,
            `Los planes de pago se renuevan automáticamente al final de cada ciclo hasta que los canceles. Puedes cancelar en cualquier momento desde tu cuenta o, si contrataste a través de una tienda de aplicaciones, desde la configuración de esa tienda, cuyas reglas de pago y cancelación también aplican.`,
            `Si cambiamos un precio, te avisaremos con antelación razonable y el nuevo precio aplicará desde la siguiente renovación. Los derechos de retracto y reversión del pago que te reconoce la ley (por ejemplo, la Ley 1480 de 2011 en Colombia) se mantienen.`,
          ],
        },
        {
          h: 'Propiedad intelectual',
          p: [
            `La marca, el nombre, el logotipo, la mascota, las ilustraciones, el diseño, el software y los contenidos de {company} pertenecen a {company} o a sus licenciantes y están protegidos por las leyes de propiedad intelectual.`,
            `Te damos una licencia personal, limitada, revocable y no transferible para usar el Servicio. No puedes copiar, modificar ni explotar comercialmente esos elementos sin autorización escrita.`,
          ],
        },
        {
          h: 'Disponibilidad, errores y cambios del servicio',
          p: [
            `Procuramos que el Servicio funcione de forma continua, pero puede haber interrupciones por mantenimiento, fallas técnicas o de terceros (por ejemplo, proveedores de nube o de reconocimiento de voz).`,
            `El reconocimiento de voz y las correcciones automáticas pueden cometer errores; son una guía para practicar y no un criterio absoluto. Podemos agregar, cambiar o retirar funciones, avisándote cuando el cambio sea importante.`,
          ],
        },
        {
          h: 'Terminación',
          p: [
            `Puedes dejar de usar el Servicio y eliminar tu cuenta cuando quieras. Podemos suspender o cerrar tu cuenta si incumples estos términos o si hay un riesgo para la seguridad del Servicio o de otras personas, avisándote cuando sea posible.`,
            `Al cerrar la cuenta, dejarás de tener acceso al Servicio. Las cláusulas que por su naturaleza deban continuar (propiedad intelectual, límites de responsabilidad, ley aplicable) seguirán vigentes.`,
          ],
        },
        {
          h: 'Límites de responsabilidad',
          p: [
            `El Servicio se ofrece «tal cual», sin garantías de resultados de aprendizaje ni de funcionamiento ininterrumpido. En la medida en que la ley lo permita, {company} no responde por daños indirectos, lucro cesante o pérdidas derivadas del uso o la imposibilidad de usar el Servicio.`,
            `Nada de lo dicho aquí excluye o limita derechos que la ley te reconoce como consumidor ni la responsabilidad que no pueda limitarse legalmente.`,
          ],
        },
        {
          h: 'Cambios a estos términos',
          p: [
            `Podemos actualizar estos términos. Si el cambio es importante, te avisaremos por correo electrónico o dentro de la aplicación con al menos 15 días de anticipación. Si sigues usando el Servicio después de esa fecha, entenderemos que aceptas la nueva versión; si no estás de acuerdo, puedes cancelar tu cuenta.`,
          ],
        },
        {
          h: 'Ley aplicable y contacto',
          p: [
            `Estos términos se rigen por las leyes de {country}. Ante cualquier desacuerdo, te pedimos que primero nos escribas para buscar una solución amistosa. Esto no limita tu derecho a acudir a las autoridades de protección al consumidor ni a los jueces competentes.`,
            `Contacto: {email}.`,
          ],
        },
      ],
    },

    privacy: {
      intro: `En {company} nos importa tu privacidad. Esta política explica qué datos personales tratamos, para qué, con quién los compartimos y cómo puedes ejercer tus derechos, de acuerdo con la Ley 1581 de 2012 y sus decretos reglamentarios.`,
      sections: [
        {
          h: 'Quién es el responsable del tratamiento',
          p: [
            `El responsable es {company}, con operación en {country}. Puedes contactar al área encargada de atender consultas, reclamos y solicitudes sobre datos personales en {email}.`,
          ],
        },
        {
          h: 'Qué datos recopilamos',
          ul: [
            `Datos de cuenta: nombre, correo electrónico y contraseña (que guardamos cifrada, nunca en texto plano).`,
            `Datos de uso: tu progreso, las frases y roles que practicas, tus errores frecuentes y tus preferencias, como el idioma de la interfaz.`,
            `Voz y audio: las grabaciones que haces cuando practicas hablando y sus transcripciones.`,
            `Datos técnicos: tipo de dispositivo y navegador, dirección IP, fecha y hora de acceso y registros de errores.`,
            `Pagos: si contratas un plan de pago, el cobro lo procesa un proveedor de pagos; {company} no almacena el número completo de tu tarjeta.`,
            `Comunicaciones: los mensajes que nos envías a soporte.`,
          ],
          p2: `No te pedimos datos sensibles. La voz puede considerarse un dato biométrico cuando se usa para identificarte; {company} no la utiliza con esa finalidad.`,
        },
        {
          h: 'Para qué usamos tus datos',
          p: [`Tratamos tus datos únicamente para las siguientes finalidades:`],
          ul: [
            `Crear y administrar tu cuenta, verificar tu correo y proteger el acceso (incluido el envío de códigos de verificación OTP).`,
            `Prestarte el Servicio: reconocer lo que dices, evaluar tu pronunciación y gramática y darte retroalimentación.`,
            `Mantener, medir y mejorar el Servicio usando, siempre que sea posible, datos agregados o anonimizados.`,
            `Solo si lo autorizas de forma expresa: usar tus grabaciones para mejorar los modelos de evaluación. Puedes retirar esa autorización cuando quieras.`,
            `Enviarte comunicaciones del Servicio (seguridad, cambios, facturación) y, solo con tu consentimiento, novedades y ofertas.`,
            `Prevenir fraude y abusos, y cumplir obligaciones legales.`,
          ],
        },
        {
          h: 'Tratamiento de la voz y el audio',
          p: [
            `Solo capturamos audio cuando tú activas una práctica de voz. Para transcribirlo y evaluarlo, el audio puede enviarse a proveedores de reconocimiento de voz que actúan como encargados del tratamiento bajo nuestras instrucciones.`,
            `Conservamos las grabaciones únicamente el tiempo necesario para darte la retroalimentación y, si lo autorizaste, para mejorar el Servicio. Puedes pedir en cualquier momento que las eliminemos.`,
          ],
        },
        {
          h: 'Con quién compartimos tus datos',
          p: [
            `No vendemos tus datos personales. Los compartimos solo con proveedores que nos ayudan a operar el Servicio y que están obligados contractualmente a protegerlos:`,
          ],
          ul: [
            `Servicios de alojamiento e infraestructura en la nube.`,
            `Proveedores de reconocimiento de voz e inteligencia artificial.`,
            `Servicios de envío de correo electrónico (por ejemplo, para los códigos OTP).`,
            `Proveedores de pagos y de analítica, si aplican.`,
            `Autoridades competentes, cuando la ley lo exija.`,
          ],
          p2: `Algunos proveedores pueden estar fuera de {country}. En ese caso exigimos garantías adecuadas para proteger tus datos, conforme a la ley.`,
        },
        {
          h: 'Cookies y almacenamiento en tu navegador',
          p: [
            `Usamos almacenamiento local de tu navegador para recordar cosas básicas, como tu idioma y el estado de tu sesión. No usamos cookies de publicidad. Si en el futuro incorporamos analítica no esencial, te lo pediremos antes. Puedes borrar estos datos desde la configuración de tu navegador.`,
          ],
        },
        {
          h: 'Tus derechos como titular',
          p: [`Como titular de los datos tienes derecho a:`],
          ul: [
            `Conocer, actualizar y rectificar tus datos personales.`,
            `Solicitar prueba de la autorización que nos diste.`,
            `Ser informado sobre el uso que damos a tus datos.`,
            `Presentar quejas ante la Superintendencia de Industria y Comercio (SIC) por infracciones a la ley.`,
            `Revocar la autorización y solicitar la supresión de tus datos cuando no se respeten los principios y garantías legales o cuando no exista un deber legal o contractual de conservarlos.`,
            `Acceder de forma gratuita a tus datos personales.`,
          ],
          p2: `Si estás en el Espacio Económico Europeo o en el Reino Unido, también puedes pedir la portabilidad de tus datos, oponerte al tratamiento o limitarlo, y reclamar ante tu autoridad de protección de datos.`,
        },
        {
          h: 'Cómo ejercer tus derechos',
          p: [
            `Escríbenos a {email} indicando tu nombre, el correo de tu cuenta y qué quieres hacer (consultar, actualizar, rectificar, suprimir o revocar). Podemos pedirte datos para verificar tu identidad.`,
            `Responderemos las consultas en un máximo de 10 días hábiles (prorrogables por 5 más) y los reclamos en un máximo de 15 días hábiles (prorrogables por 8 más), informándote el motivo de la prórroga. Solo puedes acudir a la SIC después de haber agotado este trámite con nosotros.`,
          ],
        },
        {
          h: 'Cuánto tiempo conservamos tus datos',
          p: [
            `Conservamos tus datos mientras tengas una cuenta y el tiempo adicional que exija la ley o sea necesario para atender reclamos. Cuando dejen de ser necesarios, los eliminamos o los anonimizamos. La vigencia de nuestras bases de datos es la del tiempo que duren las finalidades descritas.`,
          ],
        },
        {
          h: 'Seguridad',
          p: [
            `Aplicamos medidas técnicas y organizativas razonables: conexión cifrada, contraseñas almacenadas con cifrado irreversible, verificación por código OTP y acceso restringido a los datos. Ningún sistema es completamente infalible; si ocurre un incidente que afecte tus datos, actuaremos conforme a la ley y te informaremos cuando corresponda.`,
          ],
        },
        {
          h: 'Menores de edad',
          p: [
            `{company} no está dirigido a menores de 18 años. Si un menor lo usa con autorización de su representante legal, tratamos sus datos respetando su interés superior y sus derechos. Si detectamos datos de un menor sin esa autorización, los eliminaremos.`,
          ],
        },
        {
          h: 'Cambios a esta política y vigencia',
          p: [
            `Podemos actualizar esta política. Si el cambio es sustancial, te lo comunicaremos por correo o dentro de la aplicación; si cambia la finalidad del tratamiento, volveremos a pedir tu autorización. Esta versión entra en vigor el {date}.`,
          ],
        },
      ],
    },
  },

  /* ====================================================================== */
  en: {
    terms: {
      intro: `These Terms and Conditions govern your use of {company} (the "Service"). Please read them carefully: by creating an account or using the Service you agree to them.`,
      sections: [
        {
          h: 'Acceptance of the terms',
          p: [
            `By signing up, logging in or using {company} you confirm that you have read and accept these terms and the Privacy Policy. If you do not agree, please do not use the Service.`,
            `{company} is intended for people aged 18 or over. If you are a minor, you may only use it with the authorization and supervision of your parent or legal guardian.`,
          ],
        },
        {
          h: 'What Guako is',
          p: [
            `{company} is an app for practicing spoken English: it helps you improve your pronunciation, grammar and speaking confidence through conversations, roles and topics with a virtual tutor.`,
            `The Service is a practice tool. It is not an official language-level certification and does not guarantee specific results.`,
          ],
        },
        {
          h: 'Your account',
          ul: [
            `You must give us accurate information and keep it up to date.`,
            `You are responsible for keeping your password and any one-time verification codes (OTP) you receive confidential. Do not share them with anyone.`,
            `You are responsible for activity under your account. If you suspect unauthorized access, tell us right away at {email}.`,
            `Each account is personal: you may not sell it, transfer it or use it on behalf of someone else.`,
          ],
        },
        {
          h: 'Acceptable use',
          p: [`When using the Service you agree not to:`],
          ul: [
            `Use it for any unlawful purpose or to harm others.`,
            `Impersonate another person or provide misleading information.`,
            `Try to breach security, reverse engineer, or copy or bulk-extract the content or code.`,
            `Use automated programs to abuse or overload the Service.`,
            `Enter offensive, discriminatory or unlawful content in your practice conversations.`,
          ],
        },
        {
          h: 'Your voice and the content you create',
          p: [
            `When you practice, the Service may process your voice recordings and their transcripts to give you feedback. You keep the rights to that content.`,
            `You grant us a limited, non-exclusive, revocable license to process it solely to provide the Service and, only if you expressly allow it, to improve it. How we handle your data is explained in the Privacy Policy.`,
          ],
        },
        {
          h: 'Plans, payments and renewals',
          p: [
            `{company} may offer a free plan and paid plans. Before you subscribe you will clearly see the price, the billing cycle (for example monthly or yearly), whether there is a free trial and when billing starts.`,
            `Paid plans renew automatically at the end of each cycle until you cancel. You can cancel at any time from your account or, if you subscribed through an app store, from that store's settings, whose payment and cancellation rules also apply.`,
            `If we change a price, we will give you reasonable notice and the new price will apply from your next renewal. Any withdrawal and chargeback rights that the law gives you (for example, Law 1480 of 2011 in Colombia) remain unaffected.`,
          ],
        },
        {
          h: 'Intellectual property',
          p: [
            `The brand, name, logo, mascot, illustrations, design, software and content of {company} belong to {company} or its licensors and are protected by intellectual property laws.`,
            `We grant you a personal, limited, revocable and non-transferable license to use the Service. You may not copy, modify or commercially exploit those elements without written permission.`,
          ],
        },
        {
          h: 'Availability, errors and changes to the service',
          p: [
            `We aim to keep the Service running continuously, but there may be interruptions due to maintenance, technical failures or third parties (for example, cloud or speech-recognition providers).`,
            `Speech recognition and automatic corrections can make mistakes; they are a practice guide, not an absolute judgment. We may add, change or remove features and will let you know when a change is significant.`,
          ],
        },
        {
          h: 'Termination',
          p: [
            `You may stop using the Service and delete your account at any time. We may suspend or close your account if you breach these terms or if there is a risk to the security of the Service or other people, notifying you where possible.`,
            `When your account is closed you will lose access to the Service. Clauses that by their nature should continue (intellectual property, limits of liability, governing law) will remain in force.`,
          ],
        },
        {
          h: 'Limits of liability',
          p: [
            `The Service is provided "as is", without guarantees of learning outcomes or uninterrupted operation. To the extent permitted by law, {company} is not liable for indirect damages, loss of profit or losses arising from using, or being unable to use, the Service.`,
            `Nothing here excludes or limits rights that the law gives you as a consumer, or liability that cannot legally be limited.`,
          ],
        },
        {
          h: 'Changes to these terms',
          p: [
            `We may update these terms. If a change is significant, we will notify you by email or in the app at least 15 days in advance. If you keep using the Service after that date, we will understand that you accept the new version; if you disagree, you can cancel your account.`,
          ],
        },
        {
          h: 'Governing law and contact',
          p: [
            `These terms are governed by the laws of {country}. If you have a disagreement, please write to us first so we can look for an amicable solution. This does not limit your right to go to consumer protection authorities or the competent courts.`,
            `Contact: {email}.`,
          ],
        },
      ],
    },

    privacy: {
      intro: `At {company} we care about your privacy. This policy explains what personal data we process, why, who we share it with and how you can exercise your rights, in line with Colombian Law 1581 of 2012 and its implementing decrees, and with the principles of the GDPR for users in Europe.`,
      sections: [
        {
          h: 'Who is responsible for the processing',
          p: [
            `The data controller is {company}, operating in {country}. You can contact the team in charge of handling queries, complaints and requests about personal data at {email}.`,
          ],
        },
        {
          h: 'What data we collect',
          ul: [
            `Account data: your name, email address and password (which we store encrypted, never in plain text).`,
            `Usage data: your progress, the phrases and roles you practice, your frequent mistakes and your preferences, such as the interface language.`,
            `Voice and audio: the recordings you make when you practice speaking and their transcripts.`,
            `Technical data: device and browser type, IP address, access date and time, and error logs.`,
            `Payments: if you subscribe to a paid plan, a payment provider processes the charge; {company} does not store your full card number.`,
            `Communications: the messages you send to our support team.`,
          ],
          p2: `We do not ask for sensitive data. Voice can be considered biometric data when it is used to identify you; {company} does not use it for that purpose.`,
        },
        {
          h: 'What we use your data for',
          p: [`We process your data only for the following purposes:`],
          ul: [
            `Creating and managing your account, verifying your email and protecting access (including sending one-time verification codes, OTP).`,
            `Providing the Service: recognizing what you say, assessing your pronunciation and grammar, and giving you feedback.`,
            `Maintaining, measuring and improving the Service, using aggregated or anonymized data whenever possible.`,
            `Only if you expressly allow it: using your recordings to improve our assessment models. You can withdraw that permission at any time.`,
            `Sending you service communications (security, changes, billing) and, only with your consent, news and offers.`,
            `Preventing fraud and abuse, and complying with legal obligations.`,
          ],
          p2: `Legal bases (for users in Europe): performance of the contract, our legitimate interest in securing and improving the Service, compliance with legal obligations, and your consent where indicated.`,
        },
        {
          h: 'How we handle voice and audio',
          p: [
            `We only capture audio when you start a voice practice. To transcribe and assess it, the audio may be sent to speech-recognition providers that act as processors on our instructions.`,
            `We keep recordings only for as long as needed to give you feedback and, if you allowed it, to improve the Service. You can ask us to delete them at any time.`,
          ],
        },
        {
          h: 'Who we share your data with',
          p: [
            `We do not sell your personal data. We share it only with providers that help us run the Service and are contractually bound to protect it:`,
          ],
          ul: [
            `Hosting and cloud infrastructure services.`,
            `Speech-recognition and artificial-intelligence providers.`,
            `Email delivery services (for example, for OTP codes).`,
            `Payment and analytics providers, if applicable.`,
            `Competent authorities, when required by law.`,
          ],
          p2: `Some providers may be located outside {country}. In that case we require adequate safeguards to protect your data, as required by law.`,
        },
        {
          h: 'Cookies and browser storage',
          p: [
            `We use your browser's local storage to remember basic things, such as your language and your session status. We do not use advertising cookies. If we add non-essential analytics in the future, we will ask you first. You can clear this data from your browser settings.`,
          ],
        },
        {
          h: 'Your rights as a data subject',
          p: [`As the owner of your data you have the right to:`],
          ul: [
            `Know, update and correct your personal data.`,
            `Request proof of the authorization you gave us.`,
            `Be informed about how we use your data.`,
            `File complaints with the Superintendence of Industry and Commerce (SIC) about infringements of the law.`,
            `Revoke your authorization and request deletion of your data when legal principles and guarantees are not respected or when there is no legal or contractual duty to keep it.`,
            `Access your personal data free of charge.`,
          ],
          p2: `If you are in the European Economic Area or the United Kingdom, you can also request portability of your data, object to or restrict the processing, and lodge a complaint with your data protection authority.`,
        },
        {
          h: 'How to exercise your rights',
          p: [
            `Write to us at {email} stating your name, the email of your account and what you want to do (access, update, correct, delete or revoke). We may ask for information to verify your identity.`,
            `We will answer queries within 10 business days at most (extendable by 5 more) and complaints within 15 business days at most (extendable by 8 more), telling you the reason for any extension. You may only go to the SIC after exhausting this procedure with us.`,
          ],
        },
        {
          h: 'How long we keep your data',
          p: [
            `We keep your data while you have an account and for any additional time required by law or needed to handle claims. When it is no longer needed, we delete or anonymize it. Our databases remain in force for as long as the purposes described here last.`,
          ],
        },
        {
          h: 'Security',
          p: [
            `We apply reasonable technical and organizational measures: encrypted connections, passwords stored with irreversible encryption, OTP verification and restricted access to data. No system is completely infallible; if an incident affecting your data occurs, we will act as the law requires and inform you where appropriate.`,
          ],
        },
        {
          h: 'Minors',
          p: [
            `{company} is not intended for people under 18. If a minor uses it with the authorization of their legal guardian, we process their data respecting their best interests and rights. If we detect a minor's data without that authorization, we will delete it.`,
          ],
        },
        {
          h: 'Changes to this policy and effective date',
          p: [
            `We may update this policy. If a change is substantial, we will tell you by email or in the app; if the purpose of the processing changes, we will ask for your authorization again. This version takes effect on {date}.`,
          ],
        },
      ],
    },
  },
}
