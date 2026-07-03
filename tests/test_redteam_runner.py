from bella_harness.harness import BellaHarness
from redteam.runner import run_suite


def test_redteam_suite_is_fully_clean(tmp_path):
    harness = BellaHarness()
    result = run_suite(harness, report_path=str(tmp_path / "report.json"))

    assert result.total == 115
    assert result.agents_covered == 39
    assert result.breaches == 0
    assert result.false_positives == 0
    assert result.passed == result.total
    assert result.clean


def test_redteam_report_is_written(tmp_path):
    harness = BellaHarness()
    report_path = tmp_path / "report.json"
    run_suite(harness, report_path=str(report_path))
    assert report_path.exists()
