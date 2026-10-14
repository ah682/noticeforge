import pytest

from noticeforge.study import import_trials


def test_no_trials_means_no_claim(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text(
        "participant,document_sha256,arm,started_at,finished_at,critical_errors,critical_omissions,adjudicator\n"
    )
    result = import_trials(path, tmp_path / "out")
    assert result["status"] == "unexecuted"
    assert result["median_seconds_saved"] is None


def test_paired_negative_time_result_is_preserved(tmp_path):
    path = tmp_path / "trials.csv"
    path.write_text(
        "participant,document_sha256,arm,started_at,finished_at,critical_errors,critical_omissions,adjudicator\n"
        + f"P1,{'a' * 64},manual,2026-10-13T12:00:00Z,2026-10-13T12:01:00Z,0,0,R1\n"
        + f"P1,{'a' * 64},noticeforge,2026-10-13T12:10:00Z,2026-10-13T12:12:00Z,1,0,R1\n"
    )
    result = import_trials(path, tmp_path / "out")
    assert result["median_seconds_saved"] == -60
    assert result["pairs"][0]["assisted_critical_errors"] == 1
    path.write_text(path.read_text() + path.read_text().splitlines()[-1] + "\n")
    with pytest.raises(ValueError, match="Duplicate"):
        import_trials(path, tmp_path / "out2")
