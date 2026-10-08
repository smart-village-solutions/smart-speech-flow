/**
 * The four content routes as the gateway answers them (PR 5), with the values
 * of the production Studio bodies in tests/fixtures/studio_v2. Browser-route
 * shapes, not Studio's: a fixture in Studio's shape would hide mapper bugs.
 */
const INSTALLATION_REVISION =
  'sha256:352bfa1fce39de520625d95bc1b69df5fba423ec15f78544c54da49fc8fee666';
const KASSEL_REVISION = 'sha256:302a620a286580ceae9a5e0404c71c97b79c42a023b479a979e41475b309e60e';

/** Opaque to the browser: the revision plus a digest of the body. */
export const INSTALLATION_ETAG = `"${INSTALLATION_REVISION}.0f1e2d3c4b5a6978"`;

const kasselBranding = {
  logo: {
    url: 'https://dialog.kassel.de/assets/Logo.png',
    alternativeText: 'Logo KasselDIALOG',
  },
  icon: {
    url: 'https://dialog.kassel.de/favicon-200x200.png',
    alternativeText: 'Icon',
  },
};

/** The installation's German form; the staff form differs only in its placeholder. */
const germanFeedback = {
  headline: 'Feedback geben',
  questions: [
    {
      id: 'translationQuality',
      headline: 'Übersetzungsqualität',
      question: 'Wie genau waren die Übersetzungen?',
      required: true,
      type: 'rating',
      min: 1,
      max: 5,
    },
    {
      id: 'performance',
      headline: 'Geschwindigkeit',
      question: 'Wie schnell und reaktionsschnell war die App?',
      required: true,
      type: 'rating',
      min: 1,
      max: 5,
    },
    {
      id: 'usability',
      headline: 'Bedienung',
      question: 'Wie einfach und angenehm war die Bedienung?',
      required: true,
      type: 'rating',
      min: 1,
      max: 5,
    },
    {
      id: 'recommendation',
      headline: 'Weiterempfehlung',
      question:
        'Wie wahrscheinlich empfehlen Sie KasselDIALOG einer Kollegin oder einem Kollegen weiter?',
      required: true,
      type: 'scale',
      min: 0,
      max: 10,
      minLabel: 'Sehr unwahrscheinlich',
      maxLabel: 'Sehr wahrscheinlich',
    },
    {
      id: 'improvementIdeas',
      headline: 'Verbesserungsvorschläge',
      question: 'Was würde KasselDIALOG noch besser machen?',
      required: false,
      type: 'longText',
      placeholder: 'Ihre Ideen und Wünsche oder alles andere, was Sie uns mitteilen möchten.',
      maxLength: 4000,
    },
  ],
  noticeHtml:
    '<p>Ihre Angaben werden ausschließlich zur Verbesserung von KasselDIALOG ausgewertet.</p><p>Wir speichern das Feedback zwölf Monate lang und löschen es danach automatisch.</p><p>Sie können Ihr Feedback jederzeit widerrufen lassen – wenden Sie sich dazu an das Personal vor Ort.</p>',
  button: 'Feedback senden',
};

export const installationBody = {
  revision: INSTALLATION_REVISION,
  // Installation and tenant share their logo and icon on production.
  branding: kasselBranding,
  legal: {
    imprintUrl: 'https://www.kassel.de/impressum.php',
    privacyPolicyUrl: 'https://www.kassel.de/datenschutzerklaerung.php',
    accessibilityStatementUrl: 'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php',
  },
  locale: 'de-DE',
  startpage: {
    enterCode: 'Code eingeben',
    send: 'Weiter',
    login: 'Login für Nutzer',
  },
  login: {
    headline: 'Login',
    descriptionHtml:
      '<p>Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.</p><p></p>',
  },
  feedback: germanFeedback,
};

export const GUEST_LANGUAGE_CODES = ['en', 'ar', 'tr', 'ru', 'uk', 'am', 'ti', 'ku', 'fa'] as const;

const NAMES: Record<string, [string, string]> = {
  en: ['English', 'English'],
  ar: ['Arabic', 'العربية'],
  tr: ['Turkish', 'Türkçe'],
  ru: ['Russian', 'Русский'],
  uk: ['Ukrainian', 'Українська'],
  am: ['Amharic', 'አማርኛ'],
  ti: ['Tigrinya', 'ትግርኛ'],
  ku: ['Kurdish', 'Kurmancî'],
  fa: ['Persian', 'فارسی'],
};

/** Kassel provides English only, as on production. */
export const guestLanguagesBody = {
  languages: GUEST_LANGUAGE_CODES.map((code) => {
    const [name, native] = NAMES[code];
    return code === 'en'
      ? {
          code,
          name,
          native,
          provided: true,
          nativeName: 'English',
          icon: { url: 'https://dialog.kassel.de/flags/gb.png', alternativeText: 'Flag EN' },
        }
      : { code, name, native, provided: false };
  }),
};

const englishGuestContent = {
  storage: { mode: 'ask' },
  provided: true,
  revision: KASSEL_REVISION,
  explanationHtml:
    '<p>KasselDIALOG is an automatic real-time language translation service designed to support conversations between people who speak different languages. The service runs exclusively on a dedicated private server.</p><p>To start recording, tap the microphone button. You will then have 20 seconds to speak your input. You can also end the recording earlier with another tap. Alternatively, you can use the text input instead.</p><p>By default, audio and transcription data are processed only during the active session and are not retained afterwards. Once the conversation ends, the data is discarded automatically. You can report issues or share ideas for improvement at any time using the in-app feedback function.</p><p>If you would like to help us improve KasselDIALOG, you have the option to allow your conversation data to be stored for up to 180 days. This data may be used solely for analysis and quality improvement purposes within the KasselDIALOG project.</p>',
  storageQuestionHtml:
    '<p>I agree to the storage of my conversation data for up to 180 days for the purpose of improving KasselDIALOG.</p>',
  feedback: {
    headline: 'Share your feedback',
    questions: [
      {
        id: 'translationQuality',
        headline: 'Translation quality',
        question: 'How accurate were the translations?',
        required: true,
        type: 'rating',
        min: 1,
        max: 5,
      },
      {
        id: 'performance',
        headline: 'Performance',
        question: 'How fast and responsive did the app feel?',
        required: true,
        type: 'rating',
        min: 1,
        max: 5,
      },
      {
        id: 'usability',
        headline: 'UI / UX',
        question: 'How easy and pleasant was the interface to use?',
        required: true,
        type: 'rating',
        min: 1,
        max: 5,
      },
      {
        id: 'recommendation',
        headline: 'Recommendation',
        question: 'How likely are you to recommend KasselDIALOG to a colleague?',
        required: true,
        type: 'scale',
        min: 0,
        max: 10,
        minLabel: 'Not at all likely',
        maxLabel: 'Extremely likely',
      },
      {
        id: 'improvementIdeas',
        headline: 'Improvement ideas',
        question: 'What would make KasselDIALOG even better?',
        required: false,
        type: 'longText',
        placeholder: 'Your ideas or complaints',
        maxLength: 4000,
      },
    ],
    noticeHtml:
      '<p>Your answers are used only to improve KasselDIALOG.</p><p>We keep feedback for twelve months and delete it automatically after that.</p><p>You can have your feedback withdrawn at any time — just ask a member of staff.</p>',
    button: 'Send feedback',
  },
};

export function guestContentBody(language: string) {
  return language === 'en' ? englishGuestContent : { storage: { mode: 'ask' }, provided: false };
}

export const staffContentBody = {
  revision: KASSEL_REVISION,
  timeZone: 'Europe/Berlin',
  branding: kasselBranding,
  staff: {
    locale: 'de-DE',
    dashboard: {
      headline: 'Willkommen bei KasselDIALOG',
      explanationHtml:
        '<p>KasselDIALOG stellt einen virtuellen Echtzeit-Dolmetscher bereit. Starten Sie ein neues Gespräch, um sofort mit einer anderssprachigen Person zu kommunizieren — ohne Wartezeit und ohne Vorkenntnisse.</p>',
      callToAction: 'Neues Gespräch starten',
      load: {
        headline: 'Systemauslastung',
        green: 'Ausreichend Kapazitäten verfügbar',
        yellow: 'Das System ist stark ausgelastet, es könnte zu Verzögerungen kommen.',
        red: 'Derzeit ist das System zu stark ausgelastet, es sind keine neuen Gespräche möglich.',
      },
    },
    newConversation: {
      headline: 'Neues Gespräch',
      descriptionHtml: '<p>Code oder Link mit dem Gesprächspartner teilen</p>',
    },
    feedback: {
      ...germanFeedback,
      questions: germanFeedback.questions.map((question) =>
        question.id === 'improvementIdeas'
          ? { ...question, placeholder: 'Ihre Ideen oder Beschwerden sind willkommen.' }
          : question
      ),
    },
  },
  guestLanguageNames: { en: 'Englisch' },
};
