"""Rewrite text into a form a voice can speak.

Piper voices read plain integers through espeak-ng, which inflects them, so
only what espeak misreads is rewritten: thousands separators, clock times,
money with cents, phone numbers and German days of the month. MMS voices were
trained on text without digits and drop or garble them, so for those every
number is spelled out, decimals with a point word. The Amharic and Tigrinya
number words await review by a native speaker.
"""

import re

# Arabic-Indic and Persian digits, and the Arabic decimal and thousands signs.
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")

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
# The decimal sign where the language has a settled one; the other sign groups
# thousands there. Elsewhere either sign may group ("0,125" stays a decimal).
_DECIMAL_SIGN = {"de": ",", "tr": ",", "ru": ",", "uk": ",", "en": "."}

# Only where a time is clearly meant do clock words ("Uhr", "o'clock") get added;
# "Ergebnis 10:15" is a score.
_TIME_CONTEXT = {
    "de": (r"um|ab|bis|gegen|von|vor|nach|seit|zwischen", r"Uhr\b"),
    "en": (r"at|from|until|till|to|by|before|after|around|between", r"[ap]\.?m\.?(?!\w)"),
}

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
        "point": "ነጥብ",
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
        "point": "ነጥቢ",
    },
}


class UnspeakableTextError(ValueError):
    """The text contains nothing the voice can pronounce."""


def normalize_for_speech(text: str, lang: str, *, spell_numbers: bool) -> str:
    text = text.translate(_EASTERN_DIGITS)
    text = _rewrite_times(text, lang)
    text = _drop_group_separators(text, lang)
    text = _rewrite_money(text, lang)
    text = _rewrite_digit_sequences(text)
    if lang == "de":
        text = _rewrite_german_days(text)
    if spell_numbers and lang in _ETHIOPIC:
        text = _spell_ethiopic_numbers(text, lang)
    return " ".join(text.split())


def _drop_group_separators(text: str, lang: str) -> str:
    """Remove thousands separators: a sign followed by exactly three digits."""
    decimal = _DECIMAL_SIGN.get(lang)
    sign = "[.,]" if decimal is None else re.escape("," if decimal == "." else ".")
    grouped = rf"(?<![\d.,])[1-9]\d{{0,2}}({sign})\d{{3}}(?:\1\d{{3}})*(?!\d)(?!\1\d)"
    return re.sub(grouped, lambda match: re.sub(r"[.,]", "", match.group()), text)


def _spoken_time(hour: int, minute: int, lang: str, timed: bool) -> str:
    if timed and lang == "de":
        return f"{hour} Uhr {minute}" if minute else f"{hour} Uhr"
    if timed and lang == "en":
        if not minute:
            return f"{hour} o'clock"
        return f"{hour} oh {minute}" if minute < 10 else f"{hour} {minute}"
    if lang in _TIME_CONTEXT or minute:
        return f"{hour} {minute}"
    return str(hour)


def _rewrite_times(text: str, lang: str) -> str:
    before, after = _TIME_CONTEXT.get(lang, (r"(?!)", r"(?!)"))
    pattern = (
        rf"(?P<before>\b(?:{before})\s+)?(?<!\d)(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})(?!\d)"
        rf"(?P<after>\s*(?:{after}))?"
    )

    def replace(match: re.Match[str]) -> str:
        hour, minute = int(match["hour"]), int(match["minute"])
        if minute > 59 or (hour > 23 and not (hour == 24 and minute == 0)):
            return match.group()
        # ":00" after an hour is a time even without a preposition; scores
        # almost never end in it.
        timed = bool(match["before"] or match["after"]) or minute == 0
        spoken = _spoken_time(hour, minute, lang, timed)
        # "Uhr" is part of the spoken German time; "am"/"pm" stay.
        trailing = match["after"] if match["after"] and lang != "de" else ""
        return f"{match['before'] or ''}{spoken}{trailing}"

    return re.sub(pattern, replace, text, flags=re.IGNORECASE)


def _rewrite_money(text: str, lang: str) -> str:
    word = _EURO.get(lang, "euro")

    def spoken(match: re.Match[str]) -> str:
        units, cents = re.sub(r"[.,]", "", match.group(1)), match.group(2)
        if cents and cents != "00":
            return f"{units} {word} {cents}"
        return f"{units} {word}"

    # Anchored to the start of a digit run and possessive: unanchored, a long
    # run of digits is retried from every position (30 s for 40 000 digits).
    # Money never has three decimal places, so a three-digit group is thousands
    # whatever the language's decimal sign ("€1,000" in Russian).
    amount = r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+(?!\d)|\d++)(?:[.,](\d{2}))?(?!\d)"
    text = re.sub(rf"€\s?{amount}", spoken, text)
    text = re.sub(rf"{amount}\s?€", spoken, text)
    return re.sub(rf"(?<![\d.,])(\d++)[.,](\d{{2}})(?!\d)\s+{re.escape(word)}\b", spoken, text)


def _rewrite_digit_sequences(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        groups = re.split(r"[ /-]", match.group())
        return ", ".join(" ".join(group) for group in groups)

    # "-" and "/" join any group; a space only joins a group of three or more
    # digits, so "PLZ 01067 25 Personen" keeps its 25.
    return re.sub(r"(?<![\d.,])0\d{2,}+(?:[/-]\d{2,}+| \d{3,}+)*(?![\d.,]\d)", replace, text)


def _rewrite_german_days(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        day = int(match["day"])
        if not 1 <= day <= 31:
            return match.group()
        # "der 1. Mai" is nominative (erste); "am", "vom", "den" take -ten.
        ordinal = _german_ordinal(day, "te" if match["article"] else "ten")
        return f"{match['article'] or ''}{ordinal} {match['month']}"

    return re.sub(
        rf"(?P<article>\b[Dd]er\s+)?(?<!\d)(?P<day>\d{{1,2}})\.\s*(?P<month>{_GERMAN_MONTHS})\b",
        replace,
        text,
    )


def _german_ordinal(day: int, suffix: str) -> str:
    if day < 20:
        return f"{_GERMAN_ORDINAL_STEMS[day]}{suffix}"
    tens = "zwanzigs" if day < 30 else "dreißigs"
    unit = day % 10
    return f"{_GERMAN_UNITS[unit]}und{tens}{suffix}" if unit else f"{tens}{suffix}"


def _spell_ethiopic_numbers(text: str, lang: str) -> str:
    point = _ETHIOPIC[lang]["point"]

    def spell(match: re.Match[str]) -> str:
        parts = re.split(r"[.,]", match.group())
        if len(parts) == 2:
            fraction = " ".join(_spell_ethiopic(digit, lang) for digit in parts[1])
            return f"{_spell_ethiopic(parts[0], lang)} {point} {fraction}"
        return " ".join(_spell_ethiopic(part, lang) for part in parts)

    return re.sub(r"\d+(?:[.,]\d+)*", spell, text)


def _spell_ethiopic(digits: str, lang: str) -> str:
    words = _ETHIOPIC[lang]
    # Checked on the string: int() refuses more than 4300 digits.
    if len(digits.lstrip("0")) > 9:
        return " ".join(words["units"][int(d)] if d != "0" else words["zero"] for d in digits)
    number = int(digits)
    if number == 0:
        return words["zero"]
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


_SENTENCE_END = re.compile(r"(?<=[.!?…።؟])\s+")


def split_for_synthesis(text: str, max_chars: int = 400) -> list[str]:
    """Cut text into sentence-sized pieces of at most max_chars.

    Synthesis runs one piece at a time on the GPU, so a long message cannot
    hold the card while other languages wait, and MMS stays within the input
    lengths it handles well. Sentences are packed together up to the limit; a
    longer sentence is cut between words, a longer word hard.
    """
    chunks: list[str] = []
    current = ""
    for piece in (p for s in _SENTENCE_END.split(text) for p in _fit(s, max_chars)):
        if current and len(current) + 1 + len(piece) <= max_chars:
            current = f"{current} {piece}"
            continue
        if current:
            chunks.append(current)
        current = piece
    if current:
        chunks.append(current)
    return chunks


def _fit(sentence: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        while len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces
