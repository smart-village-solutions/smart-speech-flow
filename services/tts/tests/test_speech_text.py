import time

import pytest

from services.tts.speech_text import normalize_for_speech, split_for_synthesis


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


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("ru", "€1,000", "1000 евро"),
        ("ru", "1.000 €", "1000 евро"),
        ("uk", "Плата €1,000.", "Плата 1000 євро."),
        ("ar", "€1,000", "1000 يورو"),
        ("ar", "١٬٠٠٠ €", "1000 يورو"),
        ("fa", "€1,250,000", "1250000 یورو"),
        ("ku", "1.000 €", "1000 euro"),
        ("de", "1.000.000 Euro", "1000000 Euro"),
        ("en", "1,000,000 euros", "1000000 euros"),
    ],
)
def test_thousands_groups_are_merged_in_every_language(lang, text, expected):
    assert piper(text, lang) == expected


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("am", "1,000 ዩሮ", "ሺህ ዩሮ"),
        ("ti", "1.500 ዩሮ", "ሽሕ ሓሙሽተ ሚእቲ ዩሮ"),
        ("am", "€1,000", "ሺህ ዩሮ"),
    ],
)
def test_ethiopic_thousands_are_one_number(lang, text, expected):
    assert mms(text, lang) == expected


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("am", "3.5 ኪሎ", "ሶስት ነጥብ አምስት ኪሎ"),
        ("am", "0,25", "ዜሮ ነጥብ ሁለት አምስት"),
        ("ti", "3,5 ኪሎ", "ሰለስተ ነጥቢ ሓሙሽተ ኪሎ"),
        ("am", "ዋጋው 3.5.", "ዋጋው ሶስት ነጥብ አምስት."),
        ("am", "1.2.3", "አንድ ሁለት ሶስት"),
    ],
)
def test_ethiopic_decimals_are_read_with_a_point_word(lang, text, expected):
    assert mms(text, lang) == expected


def test_a_small_decimal_is_not_mistaken_for_a_thousands_group():
    assert piper("0,125 Liter", "de") == "0,125 Liter"


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "um 24:30", "um 24:30"),
        ("de", "bis 24:00 Uhr", "bis 24 Uhr"),
        ("de", "Ergebnis 10:15 Punkte", "Ergebnis 10 15 Punkte"),
        ("de", "ab 7:45", "ab 7 Uhr 45"),
        ("de", "Treffen 7:45 Uhr", "Treffen 7 Uhr 45"),
        ("en", "Score 10:15 today", "Score 10 15 today"),
        ("en", "from 7:05 am", "from 7 oh 5 am"),
    ],
)
def test_clock_words_are_only_added_where_a_time_is_meant(lang, text, expected):
    assert piper(text, lang) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Heute ist der 1. Mai", "Heute ist der erste Mai"),
        ("Der 3. Oktober ist ein Feiertag", "Der dritte Oktober ist ein Feiertag"),
        ("der 21. Juni", "der einundzwanzigste Juni"),
        ("der 20. Juni", "der zwanzigste Juni"),
        ("seit dem 3. Oktober", "seit dem dritten Oktober"),
    ],
)
def test_german_day_after_der_is_nominative(text, expected):
    assert piper(text, "de") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PLZ 01067 25 Personen", "PLZ 0 1 0 6 7 25 Personen"),
        ("Tel. 0621/458-90", "Tel. 0 6 2 1, 4 5 8, 9 0"),
        ("Tel. 0621-458 90", "Tel. 0 6 2 1, 4 5 8 90"),
    ],
)
def test_a_space_joins_only_groups_that_look_like_a_phone_number(text, expected):
    assert piper(text, "de") == expected


def test_short_text_is_one_chunk():
    assert split_for_synthesis("Guten Tag. Wie geht es?") == ["Guten Tag. Wie geht es?"]


def test_long_text_splits_at_sentence_ends_within_the_limit():
    sentences = [f"Satz Nummer {i} ist ein ganz normaler Satz." for i in range(30)]
    chunks = split_for_synthesis(" ".join(sentences), max_chars=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)
    assert " ".join(chunks) == " ".join(sentences)


@pytest.mark.parametrize("end", ["።", "؟", "!", "?", "…"])
def test_other_scripts_sentence_ends_are_recognised(end):
    text = f"{'ሀ' * 150}{end} {'ለ' * 150}{end}"
    assert split_for_synthesis(text, max_chars=200) == [f"{'ሀ' * 150}{end}", f"{'ለ' * 150}{end}"]


def test_a_sentence_longer_than_the_limit_is_cut_between_words():
    words = ["Wort"] * 100
    chunks = split_for_synthesis(" ".join(words), max_chars=50)
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert " ".join(chunks).split() == words


def test_a_word_longer_than_the_limit_is_cut_hard():
    assert split_for_synthesis("x" * 120, max_chars=50) == ["x" * 50, "x" * 50, "x" * 20]


def test_a_digit_run_too_long_for_int_is_read_digit_by_digit():
    spoken = mms("7" * 5000, "am")
    assert spoken.split() == ["ሰባት"] * 5000


@pytest.mark.parametrize(
    "text",
    [
        "1" * 20000 + "." + "2" * 20000 + ".",
        "1" * 30000 + " x",
        "0" + "1" * 30000 + ".5",
        "0621 " + "4589 " * 5000 + ".5",
        "€" + "1" * 30000,
    ],
    ids=["decimal", "digits", "leading-zero", "phone-groups", "euro"],
)
@pytest.mark.parametrize("lang", ["de", "ru", "am"])
def test_pathological_digit_runs_are_normalized_in_linear_time(text, lang):
    started = time.perf_counter()
    normalize_for_speech(text, lang, spell_numbers=lang == "am")
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "Termin: 14:00", "Termin: 14 Uhr"),
        ("en", "Meeting 14:00", "Meeting 14 o'clock"),
        ("de", "Ergebnis 10:15 Punkte", "Ergebnis 10 15 Punkte"),
    ],
)
def test_on_the_hour_is_a_time_even_without_a_preposition(lang, text, expected):
    assert piper(text, lang) == expected


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "Gewicht 1,500 kg", "Gewicht 1,500 kg"),
        ("de", "Es sind 2,250 Liter", "Es sind 2,250 Liter"),
        ("ru", "Вес 1,500 кг", "Вес 1,500 кг"),
        ("tr", "Ağırlık 1,500 kg", "Ağırlık 1,500 kg"),
        ("en", "It weighs 1.500 kg", "It weighs 1.500 kg"),
        ("de", "Es sind 2.250 Liter", "Es sind 2250 Liter"),
        ("en", "It weighs 1,500 kg", "It weighs 1500 kg"),
    ],
)
def test_the_languages_own_decimal_sign_is_kept(lang, text, expected):
    assert piper(text, lang) == expected


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("de", "Kosten 1.250,50 €", "Kosten 1250 Euro 50"),
        ("en", "€1,250.99", "1250 euros 99"),
        ("ru", "€1,000", "1000 евро"),
        ("uk", "1,000 €", "1000 євро"),
        ("de", "1,000 €", "1000 Euro"),
        ("en", "€1.000", "1000 euros"),
    ],
)
def test_money_never_has_three_decimal_places(lang, text, expected):
    assert piper(text, lang) == expected
