// Contenido de ejemplo para las pantallas de la app (modo demo).
// Cada plantilla es una conversación completa con su informe. Las explicaciones
// vienen en español e inglés porque el usuario elige en Ajustes en qué idioma verlas.
// Cuando exista el backend, esto lo reemplazan los datos reales.

export const TEMPLATES = {
  travel: {
    art: 'viajes',
    base: { pron: 70, gram: 66, fluency: 69, clarity: 75, listening: 80 },
    positive: {
      es: '¡Muy bien! Hablaste con ganas y tu plan de viaje se entendió desde el principio. Tu comprensión auditiva fue lo más fuerte.',
      en: 'Well done! You spoke with energy and your travel plan was clear from the start. Your listening was the strongest part.',
    },
    errors: [
      { title: { es: 'Falta “to” después de want', en: 'Missing “to” after want' }, detail: { es: 'Dijiste “want go”. Con want va “to” + verbo: “want to go”.', en: 'You said “want go”. After want use “to” + verb: “want to go”.' } },
      { title: { es: 'Artículo de más con next month', en: 'Extra article with next month' }, detail: { es: 'Con “next month” no se usa “the”.', en: 'Do not use “the” with “next month”.' } },
      { title: { es: 'Presente perfecto en lugar de pasado', en: 'Present perfect instead of past' }, detail: { es: 'Para una acción terminada con fecha (“on Monday”) usa pasado simple.', en: 'For a finished action with a date (“on Monday”) use simple past.' } },
      { title: { es: 'Pronunciación de “reservation”', en: 'Pronunciation of “reservation”' }, detail: { es: 'Suena “reh-zer-VEI-shun”, con el acento en la tercera sílaba.', en: 'It sounds “reh-zer-VAY-shun”, stressed on the third syllable.' } },
    ],
    phrases: [
      { said: 'I want go to Cartagena the next month.', better: 'I want to go to Cartagena next month.', why: { es: 'Después de “want” va “to”, y “next month” no lleva “the”.', en: 'After “want” use “to”, and “next month” takes no “the”.' } },
      { said: 'I have a reservation since Monday.', better: 'I made a reservation on Monday.', why: { es: 'La acción terminó el lunes: pasado simple con “on”.', en: 'The action finished on Monday: simple past with “on”.' } },
    ],
    words: [
      { word: 'reservation', ipa: '/ˌrezərˈveɪʃn/', tip: { es: 'Acento en “VEI”.', en: 'Stress on “VAY”.' } },
      { word: 'luggage', ipa: '/ˈlʌɡɪdʒ/', tip: { es: 'La “gg” suena como “g” suave + “dyi”.', en: 'The “gg” sounds like a soft “g” + “dj”.' } },
      { word: 'itinerary', ipa: '/aɪˈtɪnəreri/', tip: { es: 'Empieza con “ai”, no con “i”.', en: 'Starts with “eye”, not “i”.' } },
      { word: 'departure', ipa: '/dɪˈpɑːrtʃər/', tip: { es: 'La “ture” final suena “cher”.', en: 'The final “ture” sounds “cher”.' } },
      { word: 'boarding', ipa: '/ˈbɔːrdɪŋ/', tip: { es: 'La “r” es suave y la “o” es larga.', en: 'A soft “r” and a long “o”.' } },
    ],
    turns: [
      { who: 'guako', text: "Hi! I'm Guako. Where would you like to travel next?", gloss: { es: '¡Hola! Soy Guako. ¿A dónde te gustaría viajar después?', en: 'Hi! I am Guako. Where would you like to travel next?' } },
      { who: 'user', text: 'I want go to Cartagena the next month.', sec: 4, notes: [
        { frag: 'want go', better: 'want to go', why: { es: 'Después de “want” va “to” + verbo.', en: 'After “want” use “to” + verb.' } },
        { frag: 'the next month', better: 'next month', why: { es: 'Con “next month” no se usa “the”.', en: 'Do not use “the” with “next month”.' } },
      ] },
      { who: 'guako', text: 'Sounds great! How will you get there?', gloss: { es: '¡Suena genial! ¿Cómo llegarás?', en: 'Sounds great! How will you get there?' } },
      { who: 'user', text: 'I will take a flight, I have a reservation since Monday.', sec: 6, notes: [
        { frag: 'have a reservation since Monday', better: 'made a reservation on Monday', why: { es: 'Acción terminada con fecha: pasado simple.', en: 'Finished action with a date: simple past.' } },
      ] },
      { who: 'guako', text: 'Nice. What do you want to do first when you arrive?', gloss: { es: 'Qué bien. ¿Qué quieres hacer primero al llegar?', en: 'Nice. What do you want to do first when you arrive?' } },
      { who: 'user', text: 'First I want to eat seafood and visit the old city.', sec: 5, notes: [] },
      { who: 'guako', text: 'Perfect plan! Have a great trip.', gloss: { es: '¡Plan perfecto! Que tengas un gran viaje.', en: 'Perfect plan! Have a great trip.' } },
    ],
  },

  work: {
    art: 'entrevistador',
    base: { pron: 68, gram: 62, fluency: 66, clarity: 72, listening: 78 },
    positive: {
      es: '¡Buen trabajo! Respondiste con seguridad y diste ejemplos claros de tu experiencia. Se nota que conoces tus fortalezas.',
      en: 'Good job! You answered confidently and gave clear examples of your experience. You clearly know your strengths.',
    },
    errors: [
      { title: { es: 'Presente continuo con “since / for”', en: 'Present continuous with “since / for”' }, detail: { es: 'Para algo que empezó en el pasado y sigue, usa presente perfecto: “have worked for three years”.', en: 'For something that started in the past and continues, use present perfect: “have worked for three years”.' } },
      { title: { es: '“Good” en vez de “well”', en: '“Good” instead of “well”' }, detail: { es: 'Para describir cómo haces algo usa el adverbio “well”.', en: 'To describe how you do something use the adverb “well”.' } },
      { title: { es: 'Falta el artículo en “in a team”', en: 'Missing article in “in a team”' }, detail: { es: '“Team” es contable: “in a team”.', en: '“Team” is countable: “in a team”.' } },
    ],
    phrases: [
      { said: 'I am working in marketing since three years.', better: 'I have worked in marketing for three years.', why: { es: 'Acción que continúa: presente perfecto con “for”.', en: 'Ongoing action: present perfect with “for”.' } },
      { said: 'I work good in team.', better: 'I work well in a team.', why: { es: '“Well” es el adverbio y “team” necesita “a”.', en: '“Well” is the adverb and “team” needs “a”.' } },
    ],
    words: [
      { word: 'colleague', ipa: '/ˈkɑːliːɡ/', tip: { es: 'La “gue” final suena “g”.', en: 'The final “gue” sounds like “g”.' } },
      { word: 'schedule', ipa: '/ˈskedʒuːl/', tip: { es: 'Empieza con “sk”.', en: 'Starts with “sk”.' } },
      { word: 'experience', ipa: '/ɪkˈspɪriəns/', tip: { es: 'Acento en “SPI”.', en: 'Stress on “SPEER”.' } },
      { word: 'strengths', ipa: '/streŋkθs/', tip: { es: 'Practica juntar “ngth” despacio.', en: 'Practice joining “ngth” slowly.' } },
      { word: 'deadline', ipa: '/ˈdedlaɪn/', tip: { es: 'Acento en la primera sílaba.', en: 'Stress on the first syllable.' } },
    ],
    turns: [
      { who: 'guako', text: 'Welcome! Tell me about yourself and your work experience.', gloss: { es: '¡Bienvenido! Cuéntame sobre ti y tu experiencia laboral.', en: 'Welcome! Tell me about yourself and your work experience.' } },
      { who: 'user', text: 'I am working in marketing since three years.', sec: 5, notes: [
        { frag: 'am working in marketing since three years', better: 'have worked in marketing for three years', why: { es: 'Con “for + tiempo” usa presente perfecto.', en: 'With “for + time” use present perfect.' } },
      ] },
      { who: 'guako', text: 'Interesting. What are your main strengths?', gloss: { es: 'Interesante. ¿Cuáles son tus principales fortalezas?', en: 'Interesting. What are your main strengths?' } },
      { who: 'user', text: 'I am organized and I work good in team.', sec: 6, notes: [
        { frag: 'work good in team', better: 'work well in a team', why: { es: '“Well” es el adverbio; “team” lleva “a”.', en: '“Well” is the adverb; “team” takes “a”.' } },
      ] },
      { who: 'guako', text: 'Great. Why do you want this job?', gloss: { es: 'Genial. ¿Por qué quieres este trabajo?', en: 'Great. Why do you want this job?' } },
      { who: 'user', text: 'Because I want to learn and grow with the company.', sec: 5, notes: [] },
      { who: 'guako', text: 'Thank you! That was a strong interview.', gloss: { es: '¡Gracias! Fue una entrevista sólida.', en: 'Thank you! That was a strong interview.' } },
    ],
  },

  daily: {
    art: 'vida-diaria',
    base: { pron: 74, gram: 70, fluency: 72, clarity: 78, listening: 82 },
    positive: {
      es: '¡Excelente! Contaste tu día con naturalidad y con buen ritmo. Tu pronunciación se escuchó clara.',
      en: 'Excellent! You told your day naturally and at a good pace. Your pronunciation sounded clear.',
    },
    errors: [
      { title: { es: '“Go to work” sin artículo', en: '“Go to work” without article' }, detail: { es: 'Se dice “go to work”, no “go to the work”.', en: 'We say “go to work”, not “go to the work”.' } },
      { title: { es: '“Series” poco natural', en: '“Series” sounds unnatural' }, detail: { es: 'Suena más natural “TV shows”.', en: '“TV shows” sounds more natural.' } },
      { title: { es: 'Like + verbo', en: 'Like + verb' }, detail: { es: 'Después de “like” usa “to + verbo” o “verbo + -ing”.', en: 'After “like” use “to + verb” or “verb + -ing”.' } },
    ],
    phrases: [
      { said: 'I go to the work by bus.', better: 'I go to work by bus.', why: { es: '“Work” aquí no lleva artículo.', en: '“Work” takes no article here.' } },
      { said: 'I like walk in the park.', better: 'I like to walk in the park.', why: { es: 'Después de “like” va “to” + verbo.', en: 'After “like” use “to” + verb.' } },
    ],
    words: [
      { word: 'comfortable', ipa: '/ˈkʌmftərbəl/', tip: { es: 'Casi no se pronuncia la “or”.', en: 'The “or” is almost silent.' } },
      { word: 'usually', ipa: '/ˈjuːʒuəli/', tip: { es: 'La “s” suena como “zh”.', en: 'The “s” sounds like “zh”.' } },
      { word: 'vegetable', ipa: '/ˈvedʒtəbəl/', tip: { es: 'Tiene tres sílabas, no cuatro.', en: 'It has three syllables, not four.' } },
      { word: 'neighborhood', ipa: '/ˈneɪbərhʊd/', tip: { es: 'La “gh” no suena.', en: 'The “gh” is silent.' } },
      { word: 'weekend', ipa: '/ˈwiːkend/', tip: { es: 'Acento en “WEEK”.', en: 'Stress on “WEEK”.' } },
    ],
    turns: [
      { who: 'guako', text: 'Hi! Tell me about your typical day.', gloss: { es: '¡Hola! Cuéntame cómo es tu día típico.', en: 'Hi! Tell me about your typical day.' } },
      { who: 'user', text: 'I usually wake up at six and I go to the work by bus.', sec: 5, notes: [
        { frag: 'go to the work', better: 'go to work', why: { es: 'Se dice “go to work”, sin artículo.', en: 'We say “go to work”, no article.' } },
      ] },
      { who: 'guako', text: 'What do you do after work?', gloss: { es: '¿Qué haces después del trabajo?', en: 'What do you do after work?' } },
      { who: 'user', text: 'After work I cook dinner and I watch some series with my family.', sec: 6, notes: [
        { frag: 'some series', better: 'some TV shows', why: { es: '“TV shows” suena más natural.', en: '“TV shows” sounds more natural.' } },
      ] },
      { who: 'guako', text: 'Sounds relaxing. What do you like to do on weekends?', gloss: { es: 'Suena relajante. ¿Qué te gusta hacer los fines de semana?', en: 'Sounds relaxing. What do you like to do on weekends?' } },
      { who: 'user', text: 'On weekends I like walk in the park with my dog.', sec: 5, notes: [
        { frag: 'like walk', better: 'like to walk', why: { es: 'Después de “like” va “to” + verbo.', en: 'After “like” use “to” + verb.' } },
      ] },
      { who: 'guako', text: 'What a nice routine! Thanks for sharing.', gloss: { es: '¡Qué linda rutina! Gracias por compartir.', en: 'What a nice routine! Thanks for sharing.' } },
    ],
  },

  food: {
    art: 'mesero',
    base: { pron: 72, gram: 68, fluency: 71, clarity: 77, listening: 79 },
    positive: {
      es: '¡Muy bien! Pediste con claridad y sin trabarte. Lograste una conversación completa en el restaurante.',
      en: 'Very good! You ordered clearly without getting stuck. You managed a full conversation at the restaurant.',
    },
    errors: [
      { title: { es: '“Water without gas”', en: '“Water without gas”' }, detail: { es: 'En inglés se pide “still water” (sin gas) o “sparkling water”.', en: 'In English you ask for “still water” or “sparkling water”.' } },
      { title: { es: '“Recommend” sin “me”', en: '“Recommend” without “me”' }, detail: { es: 'Se dice “What do you recommend?”, sin “me”.', en: 'We say “What do you recommend?”, without “me”.' } },
      { title: { es: '“I take it” vs. “I’ll take it”', en: '“I take it” vs. “I’ll take it”' }, detail: { es: 'Para decidir en el momento usa “I’ll take it”.', en: 'To decide on the spot use “I’ll take it”.' } },
    ],
    phrases: [
      { said: 'A water without gas.', better: 'Still water, please.', why: { es: 'Así se pide agua sin gas.', en: 'This is how to ask for non-fizzy water.' } },
      { said: 'What do you recommend me?', better: 'What do you recommend?', why: { es: '“Recommend” no lleva “me”.', en: '“Recommend” takes no “me”.' } },
    ],
    words: [
      { word: 'ingredients', ipa: '/ɪnˈɡriːdiənts/', tip: { es: 'Acento en “GRII”.', en: 'Stress on “GREE”.' } },
      { word: 'recommend', ipa: '/ˌrekəˈmend/', tip: { es: 'Acento en “mend”.', en: 'Stress on “mend”.' } },
      { word: 'delicious', ipa: '/dɪˈlɪʃəs/', tip: { es: 'La “ci” suena “sh”.', en: 'The “ci” sounds “sh”.' } },
      { word: 'receipt', ipa: '/rɪˈsiːt/', tip: { es: 'La “p” no suena.', en: 'The “p” is silent.' } },
      { word: 'dessert', ipa: '/dɪˈzɜːrt/', tip: { es: 'Acento en “zert”.', en: 'Stress on “zert”.' } },
    ],
    turns: [
      { who: 'guako', text: 'Good evening! Welcome to our restaurant. What would you like to order?', gloss: { es: '¡Buenas noches! Bienvenido a nuestro restaurante. ¿Qué te gustaría pedir?', en: 'Good evening! Welcome to our restaurant. What would you like to order?' } },
      { who: 'user', text: 'I would like the chicken with rice, please, and a water without gas.', sec: 6, notes: [
        { frag: 'a water without gas', better: 'still water', why: { es: 'Así se pide agua sin gas.', en: 'This is how to ask for non-fizzy water.' } },
      ] },
      { who: 'guako', text: 'Of course. Would you like a dessert?', gloss: { es: 'Claro. ¿Te gustaría un postre?', en: 'Of course. Would you like a dessert?' } },
      { who: 'user', text: 'Yes, what do you recommend me?', sec: 3, notes: [
        { frag: 'recommend me', better: 'recommend', why: { es: '“Recommend” no lleva “me”.', en: '“Recommend” takes no “me”.' } },
      ] },
      { who: 'guako', text: 'The chocolate cake is delicious!', gloss: { es: '¡El pastel de chocolate es delicioso!', en: 'The chocolate cake is delicious!' } },
      { who: 'user', text: "Great, I'll take it. Can I have the check, please?", sec: 4, notes: [] },
      { who: 'guako', text: 'Perfect! Enjoy your meal.', gloss: { es: '¡Perfecto! Que lo disfrutes.', en: 'Perfect! Enjoy your meal.' } },
    ],
  },
}

// Temas que se pueden elegir al preparar una conversación
export const TOPICS = [
  { id: 'travel', template: 'travel', art: 'viajes' },
  { id: 'work', template: 'work', art: 'entrevistador' },
  { id: 'daily', template: 'daily', art: 'vida-diaria' },
  { id: 'food', template: 'food', art: 'mesero' },
]

export const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1']

// Prueba corta de nivel (5 preguntas): cada acierto suma
export const LEVEL_TEST = [
  { q: 'She ___ to the office every day.', es: 'Ella ___ a la oficina todos los días.', options: ['go', 'goes', 'going'], answer: 1 },
  { q: 'I ___ dinner when you called me.', es: 'Yo ___ la cena cuando me llamaste.', options: ['was cooking', 'cooked', 'am cooking'], answer: 0 },
  { q: 'If I ___ more time, I would travel more.', es: 'Si ___ más tiempo, viajaría más.', options: ['have', 'had', 'will have'], answer: 1 },
  { q: 'They have lived here ___ 2019.', es: 'Ellos viven aquí ___ 2019.', options: ['for', 'since', 'during'], answer: 1 },
  { q: 'The report ___ by the team yesterday.', es: 'El informe ___ por el equipo ayer.', options: ['wrote', 'was written', 'has wrote'], answer: 1 },
]
