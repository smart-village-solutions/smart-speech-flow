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

/** Question structure shared by every production form; only the texts differ. */
const QUESTIONS = [
  {
    id: 'translationQuality',
    type: 'rating',
    required: true,
    min: 1,
    max: 5,
  },
  {
    id: 'performance',
    type: 'rating',
    required: true,
    min: 1,
    max: 5,
  },
  {
    id: 'usability',
    type: 'rating',
    required: true,
    min: 1,
    max: 5,
  },
  {
    id: 'recommendation',
    type: 'scale',
    required: true,
    min: 0,
    max: 10,
  },
  {
    id: 'improvementIdeas',
    type: 'longText',
    required: false,
    maxLength: 4000,
  },
];

type FormTexts = {
  headline: string;
  noticeHtml: string;
  button: string;
  questions: Record<string, Record<string, string>>;
};

/** A form as the gateway sends it: every question carries its headline. */
function feedbackForm({ questions, ...form }: FormTexts) {
  return {
    ...form,
    questions: QUESTIONS.map((question) => ({ ...question, ...questions[question.id] })),
  };
}

const germanTexts: FormTexts = {
  headline: 'Feedback geben',
  noticeHtml:
    '<p>Ihre Angaben werden ausschließlich zur Verbesserung von KasselDIALOG ausgewertet.</p><p>Wir speichern das Feedback zwölf Monate lang und löschen es danach automatisch.</p><p>Sie können Ihr Feedback jederzeit widerrufen lassen – wenden Sie sich dazu an das Personal vor Ort.</p>',
  button: 'Feedback senden',
  questions: {
    translationQuality: {
      headline: 'Übersetzungsqualität',
      question: 'Wie genau waren die Übersetzungen?',
    },
    performance: {
      headline: 'Geschwindigkeit',
      question: 'Wie schnell und reaktionsschnell war die App?',
    },
    usability: {
      headline: 'Bedienung',
      question: 'Wie einfach und angenehm war die Bedienung?',
    },
    recommendation: {
      headline: 'Weiterempfehlung',
      question:
        'Wie wahrscheinlich empfehlen Sie KasselDIALOG einer Kollegin oder einem Kollegen weiter?',
      minLabel: 'Sehr unwahrscheinlich',
      maxLabel: 'Sehr wahrscheinlich',
    },
    improvementIdeas: {
      headline: 'Verbesserungsvorschläge',
      question: 'Was würde KasselDIALOG noch besser machen?',
      placeholder: 'Ihre Ideen und Wünsche oder alles andere, was Sie uns mitteilen möchten.',
    },
  },
};

const englishTexts: FormTexts = {
  headline: 'Share your feedback',
  noticeHtml:
    '<p>Your answers are used only to improve KasselDIALOG.</p><p>We keep feedback for twelve months and delete it automatically after that.</p><p>You can have your feedback withdrawn at any time — just ask a member of staff.</p>',
  button: 'Send feedback',
  questions: {
    translationQuality: {
      headline: 'Translation quality',
      question: 'How accurate were the translations?',
    },
    performance: {
      headline: 'Performance',
      question: 'How fast and responsive did the app feel?',
    },
    usability: {
      headline: 'UI / UX',
      question: 'How easy and pleasant was the interface to use?',
    },
    recommendation: {
      headline: 'Recommendation',
      question: 'How likely are you to recommend KasselDIALOG to a colleague?',
      minLabel: 'Not at all likely',
      maxLabel: 'Extremely likely',
    },
    improvementIdeas: {
      headline: 'Improvement ideas',
      question: 'What would make KasselDIALOG even better?',
      placeholder: 'Your ideas or complaints',
    },
  },
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
  feedback: feedbackForm(germanTexts),
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

type ProvidedLanguage = {
  nativeName: string;
  icon: { url: string; alternativeText: string } | null;
};

/** The nine guest languages, with Studio's entries exactly where given. */
export function guestLanguagesBodyWith(provided: Readonly<Record<string, ProvidedLanguage>>) {
  return {
    languages: GUEST_LANGUAGE_CODES.map((code) => {
      const [name, native] = NAMES[code];
      const studio = provided[code];
      return studio
        ? { code, name, native, provided: true, ...studio }
        : { code, name, native, provided: false };
    }),
  };
}

/** Kassel provides English only, as on production. */
export const guestLanguagesBody = guestLanguagesBodyWith({
  en: {
    nativeName: 'English',
    icon: { url: 'https://dialog.kassel.de/flags/gb.png', alternativeText: 'Flag EN' },
  },
});

/** Not production's icon, which is byte-identical to the bundled gb.png. */
export const STUDIO_ICON_URL = 'https://studio.example.org/flags/en.svg';

/** English texts that differ from the bundled ones, so a test can tell the source. */
export const STUDIO_ENGLISH = {
  explanationHtml:
    '<p>Studio explains the service.</p><p>Studio explains <strong>storage</strong>.</p>',
  storageQuestionHtml: '<p>Studio asks to <em>keep</em> the conversation.</p>',
};

const englishGuestContent = {
  storage: { mode: 'ask' },
  provided: true,
  revision: KASSEL_REVISION,
  explanationHtml:
    '<p>KasselDIALOG is an automatic real-time language translation service designed to support conversations between people who speak different languages. The service runs exclusively on a dedicated private server.</p><p>To start recording, tap the microphone button. You will then have 20 seconds to speak your input. You can also end the recording earlier with another tap. Alternatively, you can use the text input instead.</p><p>By default, audio and transcription data are processed only during the active session and are not retained afterwards. Once the conversation ends, the data is discarded automatically. You can report issues or share ideas for improvement at any time using the in-app feedback function.</p><p>If you would like to help us improve KasselDIALOG, you have the option to allow your conversation data to be stored for up to 180 days. This data may be used solely for analysis and quality improvement purposes within the KasselDIALOG project.</p>',
  storageQuestionHtml:
    '<p>I agree to the storage of my conversation data for up to 180 days for the purpose of improving KasselDIALOG.</p>',
  feedback: feedbackForm(englishTexts),
};

export type FixtureStorageMode = 'ask' | 'disabled' | 'unknown';

/** The gateway sends no storage question while the tenant's mode is `disabled`. */
export function guestContentBody(language: string, mode: FixtureStorageMode = 'ask') {
  if (language !== 'en') return { storage: { mode }, provided: false };
  return {
    ...englishGuestContent,
    storage: { mode },
    storageQuestionHtml: mode === 'disabled' ? null : englishGuestContent.storageQuestionHtml,
  };
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
    // The staff form differs from the installation's only in its placeholder.
    feedback: feedbackForm({
      ...germanTexts,
      questions: {
        ...germanTexts.questions,
        improvementIdeas: {
          ...germanTexts.questions.improvementIdeas,
          placeholder: 'Ihre Ideen oder Beschwerden sind willkommen.',
        },
      },
    }),
  },
  guestLanguageNames: { en: 'Englisch' },
};

/**
 * Production staff texts read almost word for word like the bundled German, so
 * a test that must tell Studio from bundled uses these instead.
 */
export const STUDIO_STAFF = {
  headline: 'Studio-Begrüßung',
  intro: 'Studio-Einleitung',
  secondParagraph: 'Studio-Absatz zwei',
  callToAction: 'Studio-Gesprächsstart',
  loadHeadline: 'Studio-Auslastung',
  green: 'Studio grün',
  yellow: 'Studio gelb',
  red: 'Studio rot',
  inviteHeadline: 'Studio-Einladung',
  inviteDescription: 'Studio-Teilen',
} as const;

const markedStaffTexts = {
  dashboard: {
    headline: STUDIO_STAFF.headline,
    explanationHtml: `<p>${STUDIO_STAFF.intro}</p><p>${STUDIO_STAFF.secondParagraph}</p>`,
    callToAction: STUDIO_STAFF.callToAction,
    load: {
      headline: STUDIO_STAFF.loadHeadline,
      green: STUDIO_STAFF.green,
      yellow: STUDIO_STAFF.yellow,
      red: STUDIO_STAFF.red,
    },
  },
  newConversation: {
    headline: STUDIO_STAFF.inviteHeadline,
    descriptionHtml: `<p>${STUDIO_STAFF.inviteDescription}</p>`,
  },
};

interface StaffContentVariant {
  locale?: string;
  timeZone?: string | null;
  guestLanguageNames?: Record<string, string>;
  /** Swap the production texts for `STUDIO_STAFF`. */
  marked?: boolean;
}

export function staffContentBodyWith({
  locale = 'de-DE',
  timeZone = 'Europe/Berlin',
  guestLanguageNames = { en: 'Englisch' },
  marked = false,
}: StaffContentVariant = {}) {
  const texts = marked ? markedStaffTexts : {};
  return {
    ...staffContentBody,
    timeZone,
    staff: { ...staffContentBody.staff, ...texts, locale },
    guestLanguageNames,
  };
}
