"""Numbers and weekdays a translation must keep from its source.

Measured on production in October 2026, the refinement LLM moved weekdays
(Persian Tuesday to Monday in 7 of 14 sentences, Albanian, Greek and
Portuguese too) while M2M100 had them right. A refinement is only allowed to
fix such facts, never to break them, and these two are the ones that can be
checked without understanding the language.
"""

import re
from collections import Counter
from typing import Dict, FrozenSet, List, Tuple

_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०१२३४५६७८९", "0123456789" * 3)

# Monday first. Stems, so inflected forms (we wtorek, kedden, четверга) match.
# Amharic, Tigrinya and Kurdish are left out until someone who reads them
# checks the names; for them only numbers are compared.
_WEEKDAYS: Dict[str, List[List[str]]] = {
    "de": [["montag"], ["dienstag"], ["mittwoch"], ["donnerstag"], ["freitag"],
           ["samstag", "sonnabend"], ["sonntag"]],
    "en": [["monday"], ["tuesday"], ["wednesday"], ["thursday"], ["friday"], ["saturday"],
           ["sunday"]],
    "ar": [["الاثنين", "الإثنين"], ["الثلاثاء"], ["الأربعاء", "الاربعاء"], ["الخميس"],
           ["الجمعة"], ["السبت"], ["الأحد", "الاحد"]],
    "tr": [["pazartesi"], ["salı"], ["çarşamba"], ["perşembe"], ["cuma"], ["cumartesi"],
           ["pazar"]],
    "ru": [["понедельник"], ["вторник"], ["сред"], ["четверг"], ["пятниц"], ["суббот"],
           ["воскресень"]],
    "uk": [["понеділ"], ["вівтор"], ["серед"], ["четвер"], ["п'ятниц", "п’ятниц"], ["субот"],
           ["неділ"]],
    "fa": [["دوشنبه", "دو شنبه", "دو‌شنبه"], ["سه‌شنبه", "سه شنبه", "سهشنبه"],
           ["چهارشنبه", "چهار شنبه", "چهار‌شنبه"],
           ["پنجشنبه", "پنج شنبه", "پنج‌شنبه"], ["جمعه"], ["شنبه"],
           ["یکشنبه", "یک شنبه", "یک‌شنبه"]],
    "it": [["lunedì", "lunedi"], ["martedì", "martedi"], ["mercoledì", "mercoledi"],
           ["giovedì", "giovedi"], ["venerdì", "venerdi"], ["sabato"], ["domenica"]],
    "ro": [["luni"], ["marți", "marţi", "marti"], ["miercuri"], ["joi"], ["vineri"],
           ["sâmbăt", "sambat"], ["duminic"]],
    "pl": [["poniedział"], ["wtor"], ["środ"], ["czwart"], ["piąt"], ["sobot"], ["niedziel"]],
    "bg": [["понеделник"], ["вторник"], ["сряда"], ["четвъртък"], ["петък"], ["събота"],
           ["неделя"]],
    "el": [["δευτέρα"], ["τρίτη"], ["τετάρτη"], ["πέμπτη"], ["παρασκευή"], ["σάββατο"],
           ["κυριακή"]],
    "fr": [["lundi"], ["mardi"], ["mercredi"], ["jeudi"], ["vendredi"], ["samedi"],
           ["dimanche"]],
    "es": [["lunes"], ["martes"], ["miércoles", "miercoles"], ["jueves"], ["viernes"],
           ["sábado", "sabado"], ["domingo"]],
    "pt": [["segunda-feira"], ["terça"], ["quarta-feira"], ["quinta-feira"], ["sexta"],
           ["sábado"], ["domingo"]],
    "sq": [["hënë"], ["martë"], ["mërkurë"], ["enjte"], ["premte"], ["shtunë"], ["diel"]],
    "hu": [["hétf"], ["kedd"], ["szerd"], ["csütörtök"], ["péntek"], ["szombat"],
           ["vasárnap"]],
    "zh": [["周一", "星期一", "礼拜一"], ["周二", "星期二", "礼拜二"], ["周三", "星期三", "礼拜三"],
           ["周四", "星期四", "礼拜四"], ["周五", "星期五", "礼拜五"], ["周六", "星期六", "礼拜六"],
           ["周日", "星期日", "星期天", "礼拜天", "周天"]],
    "hi": [["सोमवार"], ["मंगलवार"], ["बुधवार"], ["गुरुवार", "बृहस्पतिवार"], ["शुक्रवार"],
           ["शनिवार"], ["रविवार"]],
}  # fmt: skip

# Longest first: Persian یکشنبه (Sunday) contains شنبه (Saturday), Turkish
# cumartesi contains cuma.
_WEEKDAY_NAMES: Dict[str, List[Tuple[str, int]]] = {
    lang: sorted(
        ((name, day) for day, names in enumerate(days) for name in names),
        key=lambda pair: -len(pair[0]),
    )
    for lang, days in _WEEKDAYS.items()
}

Mismatch = Tuple[str, str]


def _digit_runs(text: str) -> Counter:
    """Runs of digits, so 3,50 and 3.50 agree and 350 does not. Runs of zeros
    are dropped: 70,00 € and 70 euro name the same price."""
    runs = re.findall(r"\d+", text.translate(_EASTERN_DIGITS))
    return Counter(run.lstrip("0") for run in runs if run.strip("0"))


def _weekdays(text: str, lang: str) -> FrozenSet[int]:
    remaining = text.lower()
    found = set()
    for name, day in _WEEKDAY_NAMES[lang]:
        if name in remaining:
            found.add(day)
            remaining = remaining.replace(name, " ")
    return frozenset(found)


def fact_mismatches(
    source: str, source_lang: str, translation: str, target_lang: str
) -> FrozenSet[Mismatch]:
    """What the translation names differently from the source.

    Not proof of an error on its own: a date written out with a month name
    loses a digit. Compare two translations of one source by their mismatches.
    """
    source_lang = source_lang.strip().lower().split("-", maxsplit=1)[0]
    target_lang = target_lang.strip().lower().split("-", maxsplit=1)[0]
    expected, found = _digit_runs(source), _digit_runs(translation)
    mismatches = {("missing_number", run) for run in expected if found[run] < expected[run]}
    mismatches |= {("added_number", run) for run in found if expected[run] < found[run]}
    if source_lang in _WEEKDAY_NAMES and target_lang in _WEEKDAY_NAMES:
        named = _weekdays(translation, target_lang)
        if named != _weekdays(source, source_lang):
            mismatches.add(("weekdays", ",".join(map(str, sorted(named)))))
    return frozenset(mismatches)


def refinement_changes_facts(
    source: str, source_lang: str, candidate: str, refined: str, target_lang: str
) -> bool:
    """Whether the refinement names a number or weekday the candidate did not
    get wrong already. A mismatch both share (a date written out with a month
    name) is not the refinement's doing."""
    before = fact_mismatches(source, source_lang, candidate, target_lang)
    return not fact_mismatches(source, source_lang, refined, target_lang) <= before
