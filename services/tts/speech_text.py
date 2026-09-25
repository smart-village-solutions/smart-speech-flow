"""Rewrite text into a form a voice can speak.

Piper voices read plain integers through espeak-ng, which inflects them, so
only what espeak misreads is rewritten: clock times, money with cents, phone
numbers and German days of the month. MMS voices were trained on text without
digits and drop or garble them, so for those every integer is spelled out.
The Amharic and Tigrinya number words await review by a native speaker.
"""

import re

_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_EURO = {
    "de": "Euro",
    "en": "euros",
    "tr": "avro",
    "ru": "евро",
    "uk": "євро",
    "ar": "يورو",
    "fa": "یورو",
    "ku": "euro",
    "am": "ዩሮ",
    "ti": "ዩሮ",
}
_THOUSANDS_SEPARATOR = {"de": ".", "tr": ".", "en": ","}

_GERMAN_MONTHS = (
    "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
)
_GERMAN_ORDINAL_STEMS = [
    "",
    "ers",
    "zwei",
    "drit",
    "vier",
    "fünf",
    "sechs",
    "sieb",
    "ach",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
    "vierzehn",
    "fünfzehn",
    "sechzehn",
    "siebzehn",
    "achtzehn",
    "neunzehn",
]
_GERMAN_UNITS = ["", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"]

_ETHIOPIC = {
    "am": {
        "zero": "ዜሮ",
        "units": ["", "አንድ", "ሁለት", "ሶስት", "አራት", "አምስት", "ስድስት", "ሰባት", "ስምንት", "ዘጠኝ"],
        "ten": "አስር",
        "teen": "አስራ",
        "tens": ["", "", "ሃያ", "ሰላሳ", "አርባ", "ሃምሳ", "ስልሳ", "ሰባ", "ሰማንያ", "ዘጠና"],
        "hundred": "መቶ",
        "thousand": "ሺህ",
        "million": "ሚሊዮን",
    },
    "ti": {
        "zero": "ዜሮ",
        "units": ["", "ሓደ", "ክልተ", "ሰለስተ", "ኣርባዕተ", "ሓሙሽተ", "ሽዱሽተ", "ሸውዓተ", "ሸሞንተ", "ትሽዓተ"],
        "ten": "ዓሰርተ",
        "teen": "ዓሰርተ",
        "tens": ["", "", "ዕስራ", "ሰላሳ", "ኣርብዓ", "ሓምሳ", "ስሳ", "ሰብዓ", "ሰማንያ", "ቴስዓ"],
        "hundred": "ሚእቲ",
        "thousand": "ሽሕ",
        "million": "ሚልዮን",
    },
}


class UnspeakableTextError(ValueError):
    """The text contains nothing the voice can pronounce."""


def normalize_for_speech(text: str, lang: str, *, spell_numbers: bool) -> str:
    text = text.translate(_EASTERN_DIGITS)
    text = _rewrite_times(text, lang)
    text = _drop_thousands_separators(text, lang)
    text = _rewrite_money(text, lang)
    text = _rewrite_digit_sequences(text)
    if lang == "de":
        text = _rewrite_german_days(text)
    if spell_numbers and lang in _ETHIOPIC:
        text = re.sub(r"\d+", lambda match: _spell_ethiopic(match.group(), lang), text)
    return " ".join(text.split())


def _spoken_time(hour: int, minute: int, lang: str) -> str:
    if lang == "de":
        return f"{hour} Uhr {minute}" if minute else f"{hour} Uhr"
    if lang == "en":
        if not minute:
            return f"{hour} o'clock"
        return f"{hour} oh {minute}" if minute < 10 else f"{hour} {minute}"
    return f"{hour} {minute}" if minute else str(hour)


def _rewrite_times(text: str, lang: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 24 or minute > 59:
            return match.group()
        return _spoken_time(hour, minute, lang)

    pattern = r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)"
    if lang == "de":
        pattern += r"(?:\s*Uhr\b)?"
    return re.sub(pattern, replace, text)


def _drop_thousands_separators(text: str, lang: str) -> str:
    separator = _THOUSANDS_SEPARATOR.get(lang)
    if separator is None:
        return text
    sep = re.escape(separator)
    grouped = rf"(?<![\d{sep}])\d{{1,3}}(?:{sep}\d{{3}})+(?![\d]|{sep}\d)"
    return re.sub(grouped, lambda match: match.group().replace(separator, ""), text)


def _rewrite_money(text: str, lang: str) -> str:
    word = _EURO.get(lang, "euro")

    def spoken(match: re.Match[str]) -> str:
        units, cents = match.group(1), match.group(2)
        if cents and cents != "00":
            return f"{units} {word} {cents}"
        return f"{units} {word}"

    amount = r"(\d+)(?:[.,](\d{2}))?(?!\d)"
    text = re.sub(rf"€\s?{amount}", spoken, text)
    text = re.sub(rf"{amount}\s?€", spoken, text)
    return re.sub(rf"(\d+)[.,](\d{{2}})(?!\d)\s+{re.escape(word)}\b", spoken, text)


def _rewrite_digit_sequences(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        groups = re.split(r"[ /-]", match.group())
        return ", ".join(" ".join(group) for group in groups)

    return re.sub(r"(?<![\d.,])0\d{2,}(?:[ /-]\d{2,})*(?![\d.,]\d)", replace, text)


def _rewrite_german_days(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        day = int(match.group(1))
        if not 1 <= day <= 31:
            return match.group()
        return f"{_german_ordinal(day)} {match.group(2)}"

    return re.sub(rf"(?<!\d)(\d{{1,2}})\.\s*({_GERMAN_MONTHS})\b", replace, text)


def _german_ordinal(day: int) -> str:
    if day < 20:
        return f"{_GERMAN_ORDINAL_STEMS[day]}ten"
    tens = "zwanzigsten" if day < 30 else "dreißigsten"
    unit = day % 10
    return f"{_GERMAN_UNITS[unit]}und{tens}" if unit else tens


def _spell_ethiopic(digits: str, lang: str) -> str:
    words = _ETHIOPIC[lang]
    number = int(digits)
    if number == 0:
        return words["zero"]
    if number >= 1_000_000_000:
        return " ".join(words["units"][int(d)] if d != "0" else words["zero"] for d in digits)
    parts = []
    for scale, name in ((1_000_000, "million"), (1_000, "thousand")):
        count, number = divmod(number, scale)
        if count:
            parts.append(
                words[name] if count == 1 else f"{_below_1000(count, words)} {words[name]}"
            )
    if number:
        parts.append(_below_1000(number, words))
    return " ".join(parts)


def _below_1000(number: int, words: dict) -> str:
    hundreds, rest = divmod(number, 100)
    parts = []
    if hundreds:
        hundred = words["hundred"]
        parts.append(hundred if hundreds == 1 else f"{words['units'][hundreds]} {hundred}")
    if rest:
        parts.append(_below_100(rest, words))
    return " ".join(parts)


def _below_100(number: int, words: dict) -> str:
    if number < 10:
        return words["units"][number]
    if number == 10:
        return words["ten"]
    if number < 20:
        return f"{words['teen']} {words['units'][number - 10]}"
    tens, unit = divmod(number, 10)
    return f"{words['tens'][tens]} {words['units'][unit]}" if unit else words["tens"][tens]
