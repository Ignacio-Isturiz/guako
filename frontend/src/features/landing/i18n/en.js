export default {
  meta: {
    title: 'Guako — Speak English with confidence',
    description:
      'Guako helps you speak English with confidence: improve your pronunciation, lose the shyness and fix your grammar as you speak.',
  },

  nav: {
    home: 'Guako, home',
    login: 'Log in',
    logout: 'Log out',
    app: 'My space',
    language: 'Language',
  },

  hero: {
    line1: 'Speak English ',
    with: 'with ',
    end: 'no shame.',
    lead: 'Improve your pronunciation, fix your grammar as you speak and get understood. Guako listens and helps you lose the fear.',
    start: 'Get started free',
    how: 'How it works',
    stackAria: 'Guako benefits',
  },

  benefits: [
    { title: 'Improve your pronunciation', word: 'a clear accent', text: 'Listen, repeat and sound natural.' },
    { title: 'Lose the shyness', word: 'confidence', text: 'Practice without anyone judging you.' },
    { title: 'Fix your grammar', word: 'accuracy', text: 'Guako explains your mistakes out loud.' },
    { title: 'Be understood', word: 'clarity', text: 'Get understood the first time.' },
    { title: 'Gain fluency', word: 'fluency', text: 'Chat without getting stuck for words.' },
    { title: 'Practice at your pace', word: 'your pace', text: 'Whenever you want, wherever you want.' },
    { title: 'Lose the fear of failing', word: 'courage', text: 'Making mistakes is learning too.' },
    { title: 'Speak with assurance', word: 'assurance', text: 'Interviews, trips and work without nerves.' },
  ],

  roles: {
    eyebrow: 'How it works',
    title: 'Roles and topics to talk about',
    intro: 'Choose who you want Guako to be and what you want to talk about. You practice, Guako listens and corrects you.',
    roleTag: 'Role',
    topicTag: 'Topic',
    roleList: [
      { title: 'Interviewer', text: 'Practice your job interview.' },
      { title: 'Waiter', text: 'Order and pay without feeling shy.' },
    ],
    topicList: [
      { title: 'Travel', text: 'Airports, hotels and directions.' },
      { title: 'Daily life', text: 'Everyday conversations.' },
    ],
    assetAlt: 'Guako, the parrot mascot',
    bubbleA: 'Hello!',
    bubbleB: 'Nice to meet you!',
    phrasesLabel: 'Real phrases you will practice',
    phrases: [
      { kind: 'rol', tag: 'Waiter', en: 'Could I have the check, please?', es: '¿Me trae la cuenta, por favor?' },
      { kind: 'tema', tag: 'Travel', en: 'Where is the boarding gate?', es: '¿Dónde está la puerta de embarque?' },
      { kind: 'rol', tag: 'Interviewer', en: 'Tell me about yourself.', es: 'Cuéntame sobre ti.' },
      { kind: 'tema', tag: 'Daily life', en: 'What did you do this weekend?', es: '¿Qué hiciste este fin de semana?' },
      { kind: 'tema', tag: 'Travel', en: "I'd like to book a room.", es: 'Quisiera reservar una habitación.' },
      { kind: 'rol', tag: 'Waiter', en: "I'll have the chicken, please.", es: 'Quiero el pollo, por favor.' },
      { kind: 'rol', tag: 'Interviewer', en: "I'm good at working in a team.", es: 'Soy bueno trabajando en equipo.' },
      { kind: 'tema', tag: 'Daily life', en: 'Nice to meet you!', es: '¡Mucho gusto!' },
    ],
  },

  how: {
    titleA: 'How will you ',
    titleMark: 'learn',
    titleB: '?',
    points: [
      { title: 'You really speak.', text: 'Out loud, no typing or tapping buttons.' },
      { title: 'Corrected instantly.', text: 'Guako listens and explains your mistakes.' },
      { title: 'At your own pace.', text: 'Short sessions, no pressure and nobody watching.' },
    ],
    label: 'Different options',
    options: [
      { title: 'Speak by voice', text: 'Conversations with roles.' },
      { title: 'Listen and repeat', text: 'Pronunciation phrase by phrase.' },
      { title: 'Instant correction', text: 'Grammar explained out loud.' },
      { title: 'Daily challenges', text: 'A short streak that keeps you practicing.' },
    ],
  },

  cta: {
    title: 'Start',
    titleRest: ' speaking',
    lead: 'This is what practicing with Guako looks like: you say the phrase out loud and every word is marked instantly.',
    tag: 'App preview',
    micAria: 'Watch the animation again',
    next: 'Another phrase ↻',
    idle: 'Say the phrase out loud.',
    listening: 'Listening…',
    perfect: 'Excellent! That is how a confident speaker sounds.',
    almost: 'Almost! Guako helps you with “{word}” and you repeat it.',
    start: 'Get started free',
    login: 'Log in',
  },

  footer: {
    terms: 'Terms and conditions',
    privacy: 'Privacy policy',
    rights: '© 2026 Guako',
  },

  install: {
    button: 'Install the app on your phone',
    done: 'Done! Look for Guako on your phone’s home screen.',
    close: 'Close',
    ok: 'Got it',
    title: {
      android: 'Install Guako on your Android',
      ios: 'Install Guako on your iPhone',
      desktop: 'Install Guako on your phone',
    },
    steps: {
      android: [
        'Open this page in <strong>Chrome</strong>.',
        'Tap the <strong>⋮</strong> menu at the top right.',
        'Choose <strong>Install app</strong> or <strong>Add to Home screen</strong>.',
      ],
      ios: [
        'Open this page in <strong>Safari</strong>.',
        'Tap the <strong>Share</strong> button (the square with the up arrow).',
        'Choose <strong>Add to Home Screen</strong>, then <strong>Add</strong>.',
      ],
    },
    desktop: 'Open <strong>{url}</strong> on your phone and tap <strong>Install the app on your phone</strong>: we detect whether it is Android or iPhone and take you to install it.',
    store: { android: 'Get it on Google Play', ios: 'Download on the App Store' },
  },
}
