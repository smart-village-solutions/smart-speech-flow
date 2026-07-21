from tools.benchmarks.run_pipeline_benchmark import summary


def test_summary_rates_include_successes_errors_and_timeouts():
    result = summary([100.0, 200.0], errors=1, timeouts=1)

    assert result["error_rate"] == 0.25
    assert result["timeout_rate"] == 0.25
