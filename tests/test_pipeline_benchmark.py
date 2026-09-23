import pytest

from tools.benchmarks.run_pipeline_benchmark import summary


def test_summary_rates_include_successes_errors_and_timeouts():
    result = summary([100.0, 200.0], errors=1, timeouts=1)

    assert result["error_rate"] == 0.25
    assert result["timeout_rate"] == 0.25


def test_refinement_summary_counts_each_attempt_once():
    """A failed refinement records a duration, so it is already in `values`.

    Passing it to `summary()` as an error too counts it twice and halves the
    reported rate, which is how ADR-002 came to state 45.3% for a run that
    failed 199 of 240 times.
    """
    from tools.benchmarks.run_pipeline_benchmark import refinement_summary

    results = [
        {"refinement_ms": 500.0, "refinement_status": "success"} for _ in range(41)
    ] + [{"refinement_ms": 4004.0, "refinement_status": "error"} for _ in range(199)]

    result = refinement_summary(results)

    assert result["count"] == 41
    assert result["error_rate"] == pytest.approx(199 / 240)
    assert result["median_ms"] == 500.0


def test_end_to_end_summary_still_counts_failures_in_the_denominator():
    """A failed request raises, so it never reaches `values` — unlike a
    failed refinement. The two denominators are not the same."""
    result = summary([1.0] * 3, errors=1, timeouts=0)

    assert result["error_rate"] == pytest.approx(0.25)
