# Mehrsprachige Übersetzungs-Audiofixtures

Synthetische Sprachproben für ASR- und Übersetzungs-Integrationstests. Sie
wurden mit dem lokalen TTS-Service und dessen sprachspezifischen Coqui- bzw.
MMS-Modellen erzeugt. Alle Dateien sind WAV mit 16 kHz, Mono und 16-Bit-PCM.
Die Präfixe der Dateinamen geben Quell- und Zielsprache an.

Der Unterordner [`duration_set`](duration_set/) enthält zusätzlich je eine
kurze, mittlere und lange Probe für jede vom TTS-Service unterstützte
Quellsprache (`am`, `ar`, `de`, `en`, `fa`, `ku`, `ru`, `ti`, `tr`, `uk`).
Die exakten eingesprochenen Texte und die gemessenen Dauern stehen in dessen
[`transcripts.json`](duration_set/transcripts.json).

| Datei | Sprechsprache | Sprechtext |
| --- | --- | --- |
| `a01_de_en_appointment.wav` | de | Guten Tag. Ich möchte einen Termin für die Anmeldung meines Wohnsitzes vereinbaren. |
| `a02_de_en_documents.wav` | de | Bitte bringen Sie Ihren Reisepass, die Wohnungsgeberbestätigung und, falls vorhanden, Ihre Geburtsurkunde mit. |
| `a03_en_de_registration.wav` | en | I moved to Germany last week and would like to register my new address. |
| `a04_en_de_deadline.wav` | en | Your application is complete, but we still need the original document by Friday, the twenty-seventh of March. |
| `a05_de_tr_address.wav` | de | Ihre neue Adresse wird erst nach der persönlichen Identitätsprüfung im System gespeichert. |
| `a06_de_tr_fee.wav` | de | Die Gebühr beträgt zwölf Euro und kann mit Karte oder in bar bezahlt werden. |
| `a07_tr_de_residence.wav` | tr | İkamet belgem henüz gelmedi. Geçici bir belgeyle başvuru yapabilir miyim? |
| `a08_tr_de_interpreter.wav` | tr | Görüşme sırasında Türkçe tercüman desteğine ihtiyacım var. |
| `a09_de_ar_documents.wav` | de | Für den Antrag benötigen wir eine Kopie Ihres Passes und einen aktuellen Nachweis Ihrer Krankenversicherung. |
| `a10_de_ar_appointment.wav` | de | Ihr Termin ist am Dienstag um neun Uhr dreißig im Zimmer zweihundertvierzehn. |
| `a11_ar_de_extension.wav` | ar | أرغب في تمديد إقامتي لأن عقد عملي ينتهي في نهاية شهر سبتمبر. |
| `a12_ar_de_notification.wav` | ar | لم أتلقَّ الرسالة بعد، هل يمكنكم إرسالها مرة أخرى إلى عنواني الجديد؟ |
| `a13_de_uk_family.wav` | de | Möchten Sie die Kinder gleichzeitig anmelden, oder soll für jede Person ein eigener Termin vereinbart werden? |
| `a14_de_uk_emergency.wav` | de | Wenn sich Ihre Kontaktdaten ändern, informieren Sie uns bitte innerhalb von zwei Wochen. |
| `a15_uk_de_documents.wav` | uk | У мене є закордонний паспорт, але оригінал свідоцтва про народження зараз у перекладі. |
| `a16_uk_de_accessibility.wav` | uk | Чи можу я отримати форму у доступному електронному форматі та заповнити її вдома? |
