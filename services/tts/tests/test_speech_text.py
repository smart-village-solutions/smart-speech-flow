import pytest

from services.tts.speech_text import normalize_for_speech


def piper(text, lang):
    return normalize_for_speech(text, lang, spell_numbers=False)


def mms(text, lang):
    return normalize_for_speech(text, lang, spell_numbers=True)


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "um 9:30 Uhr", "um 9 Uhr 30"),
        ("de", "um 14:00", "um 14 Uhr"),
        ("en", "at 9:30", "at 9 30"),
        ("en", "at 9:05", "at 9 oh 5"),
        ("en", "at 9:00", "at 9 o'clock"),
        ("fa", "ساعت 9:30", "ساعت 9 30"),
        ("tr", "saat 9:30'da", "saat 9 30'da"),
    ],
)
def test_clock_times_become_words_espeak_reads(lang, text, expected):
    assert piper(text, lang) == expected


def test_an_impossible_time_is_left_alone():
    assert piper("Score 31:75", "en") == "Score 31:75"


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "Die Gebühr beträgt 3,50 €.", "Die Gebühr beträgt 3 Euro 50."),
        ("de", "Das kostet 1.250,00 Euro.", "Das kostet 1250 Euro."),
        ("en", "The fee is €3.50.", "The fee is 3 euros 50."),
        ("en", "The fee is €25.", "The fee is 25 euros."),
        ("en", "It costs 3.50 euros.", "It costs 3 euros 50."),
        ("ru", "Плата 25 €.", "Плата 25 евро."),
    ],
)
def test_money_is_read_as_units_then_cents(lang, text, expected):
    assert piper(text, lang) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rufen Sie 0621 4589 an.", "Rufen Sie 0 6 2 1, 4 5 8 9 an."),
        ("Tel. 0621-458 90", "Tel. 0 6 2 1, 4 5 8, 9 0"),
        ("Zimmer 204 im 2. Stock", "Zimmer 204 im 2. Stock"),
        ("0 Euro", "0 Euro"),
    ],
)
def test_numbers_with_a_leading_zero_are_read_digit_by_digit(text, expected):
    assert piper(text, "de") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("am 15. März", "am fünfzehnten März"),
        ("bis 1. Mai", "bis ersten Mai"),
        ("am 21. Juni", "am einundzwanzigsten Juni"),
        ("am 31. Dezember", "am einunddreißigsten Dezember"),
        ("am 7. Juli", "am siebten Juli"),
        ("am 3. Oktober", "am dritten Oktober"),
    ],
)
def test_german_day_of_month_becomes_an_ordinal(text, expected):
    assert piper(text, "de") == expected


def test_plain_integers_are_left_to_espeak_for_piper_voices():
    assert piper("Zimmer 204", "de") == "Zimmer 204"


def test_eastern_arabic_digits_become_ascii():
    assert piper("الغرفة ٢٠٤", "ar") == "الغرفة 204"
    assert piper("اتاق ۲۰۴", "fa") == "اتاق 204"


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("0", "ዜሮ"),
        ("7", "ሰባት"),
        ("10", "አስር"),
        ("15", "አስራ አምስት"),
        ("21", "ሃያ አንድ"),
        ("100", "መቶ"),
        ("204", "ሁለት መቶ አራት"),
        ("1000", "ሺህ"),
        ("2026", "ሁለት ሺህ ሃያ ስድስት"),
        ("45890", "አርባ አምስት ሺህ ስምንት መቶ ዘጠና"),
        ("1000000", "ሚሊዮን"),
    ],
)
def test_amharic_numbers_are_spelled(number, expected):
    assert mms(number, "am") == expected


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("5", "ሓሙሽተ"),
        ("10", "ዓሰርተ"),
        ("15", "ዓሰርተ ሓሙሽተ"),
        ("25", "ዕስራ ሓሙሽተ"),
        ("300", "ሰለስተ ሚእቲ"),
        ("999999", "ትሽዓተ ሚእቲ ቴስዓ ትሽዓተ ሽሕ ትሽዓተ ሚእቲ ቴስዓ ትሽዓተ"),
    ],
)
def test_tigrinya_numbers_are_spelled(number, expected):
    assert mms(number, "ti") == expected


def test_mms_voices_get_times_spelled_too():
    assert mms("ሰዓት 9:30", "ti") == "ሰዓት ትሽዓተ ሰላሳ"


def test_numbers_beyond_the_speller_are_read_digit_by_digit():
    assert mms("1234567890", "am") == "አንድ ሁለት ሶስት አራት አምስት ስድስት ሰባት ስምንት ዘጠኝ ዜሮ"


def test_unknown_language_only_gets_the_generic_rules():
    assert piper("0621 4589 at 9:30", "xx") == "0 6 2 1, 4 5 8 9 at 9 30"


def test_whitespace_is_collapsed():
    assert piper("  Hallo   Welt ", "de") == "Hallo Welt"
