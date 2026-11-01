import pytest

from services.api_gateway.translation_facts import fact_mismatches


def test_a_decimal_comma_and_a_decimal_point_name_the_same_amount():
    assert not fact_mismatches("Die Gebühr beträgt 3,50 Euro.", "de", "费用为3.50欧元。", "zh")


def test_an_amount_read_as_a_whole_number_is_a_mismatch():
    assert fact_mismatches("Die Gebühr beträgt 3,50 Euro.", "de", "收费为350欧元。", "zh")


def test_a_wrong_year_is_a_mismatch():
    assert fact_mismatches(
        "Kommen Sie am 15.10.2026.", "de", "Jöjjön el 2019. október 15-én.", "hu"
    )


def test_eastern_digits_are_read_as_digits():
    assert not fact_mismatches("Das kostet 3,50 €.", "de", "هزینه ۳.۵۰ یورو است.", "fa")
    assert not fact_mismatches("Um 10 Uhr.", "de", "10 बजे।", "hi")


def test_zero_cents_may_be_dropped():
    assert not fact_mismatches("Der Pass kostet 70,00 €.", "de", "Il passaporto costa 70 euro.", "it")


def test_a_different_weekday_is_a_mismatch():
    assert fact_mismatches("am Dienstag", "de", "روز دوشنبه", "fa")


def test_the_same_weekday_in_another_spelling_matches():
    assert not fact_mismatches("am Dienstag", "de", "روز سه شنبه", "fa")
    assert not fact_mismatches("am Dienstag", "de", "روز سه‌شنبه", "fa")


@pytest.mark.parametrize(
    ("translation", "lang"),
    [
        ("یکشنبه", "fa"),  # Sunday contains the Persian word for Saturday
        ("Pazar", "tr"),  # Sunday is the start of the Turkish word for Monday
        ("Τρίτη", "el"),
        ("we wtorek", "pl"),
        ("kedden", "hu"),
        ("周日", "zh"),
    ],
)
def test_inflected_and_overlapping_weekday_names(translation, lang):
    expected = "Dienstag" if lang in ("el", "pl", "hu") else "Sonntag"
    assert not fact_mismatches(expected, "de", translation, lang)


def test_a_weekday_dropped_from_the_translation_is_a_mismatch():
    assert fact_mismatches("Kommen Sie am Freitag wieder.", "de", "Please come back.", "en")


def test_weekdays_are_not_checked_in_a_language_without_a_name_table():
    assert not fact_mismatches("am Dienstag", "de", "ሰኞ", "am")
