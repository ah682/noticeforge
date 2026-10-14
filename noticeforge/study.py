"""Import real, pseudonymous reviewer trials; empty input cannot imply time savings."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Trial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    arm: Literal["manual", "noticeforge"]
    started_at: datetime
    finished_at: datetime
    critical_errors: int = Field(ge=0)
    critical_omissions: int = Field(ge=0)
    adjudicator: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_time(self):
        if not self.started_at.tzinfo or not self.finished_at.tzinfo or self.finished_at <= self.started_at:
            raise ValueError("Trial times require time zones and a positive duration")
        return self


def import_trials(source: Path, output: Path) -> dict:
    with source.open(newline="") as file:
        trials = [Trial.model_validate(row) for row in csv.DictReader(file)]
    seen = set()
    pairs: dict[tuple[str, str], dict[str, Trial]] = {}
    for trial in trials:
        key = (trial.participant, trial.document_sha256, trial.arm)
        if key in seen:
            raise ValueError("Duplicate participant/document/arm trial")
        seen.add(key)
        pairs.setdefault(key[:2], {})[trial.arm] = trial
    comparisons = []
    seconds_saved: list[float] = []
    for (participant, document), group in pairs.items():
        if set(group) != {"manual", "noticeforge"}:
            continue
        manual, assisted = group["manual"], group["noticeforge"]
        manual_s = (manual.finished_at - manual.started_at).total_seconds()
        assisted_s = (assisted.finished_at - assisted.started_at).total_seconds()
        seconds_saved.append(manual_s - assisted_s)
        comparisons.append(
            {
                "participant": participant,
                "document_sha256": document,
                "manual_seconds": manual_s,
                "noticeforge_seconds": assisted_s,
                "seconds_saved": manual_s - assisted_s,
                "manual_critical_errors": manual.critical_errors,
                "assisted_critical_errors": assisted.critical_errors,
                "manual_critical_omissions": manual.critical_omissions,
                "assisted_critical_omissions": assisted.critical_omissions,
            }
        )
    report = {
        "status": "imported" if trials else "unexecuted",
        "trials": len(trials),
        "paired_trials": len(comparisons),
        "pairs": comparisons,
        "median_seconds_saved": median(seconds_saved) if seconds_saved else None,
        "interpretation": "Descriptive paired observations only. Randomize order; use separate matched notices "
        "to control learning. Independent engineers must adjudicate critical errors. "
        "No improvement is inferred from an empty template or synthetic benchmark.",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "study.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "trials.jsonl").write_text("".join(trial.model_dump_json() + "\n" for trial in trials))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/review-study"))
    args = parser.parse_args()
    print(json.dumps(import_trials(args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
