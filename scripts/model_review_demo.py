"""Explicit fixture-only UI verification server. It never invokes a live model."""

import argparse
import json
from pathlib import Path

import uvicorn

from noticeforge.api import create_app
from noticeforge.cli import seed


class ReviewFixtureProvider:
    name = "fixture-offline"
    model_id = "owned-review-fixture-v1"

    def generate(self, request):
        candidates = []
        for identifier, deadline in [("AMP-230-A", "2027-01-15"), ("AMP-230-B", "2027-02-15")]:
            for page in request.pages:
                start = page.text.find(identifier)
                end = page.text.find(deadline, start)
                if start >= 0 and end >= start:
                    end += len(deadline)
                    candidates.append(
                        {
                            "part_raw": identifier,
                            "date_type": "effective_change",
                            "date": deadline,
                            "date_text": deadline,
                            "exception": None,
                            "evidence": [
                                {
                                    "page": page.number,
                                    "start": start,
                                    "end": end,
                                    "quote": page.text[start:end],
                                }
                            ],
                        }
                    )
        if candidates:
            candidates.append({**candidates[0], "part_raw": "INVENTED-PART-999"})
        return json.dumps({"candidates": candidates}), {"attempts": 1, "simulation": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8878)
    parser.add_argument("--data-dir", type=Path, default=Path("/tmp/noticeforge-model-review-demo"))
    args = parser.parse_args()
    seed(args.data_dir)
    print("FIXTURE ONLY: owned hard-coded proposals for browser verification; no live AI.", flush=True)
    uvicorn.run(
        create_app(args.data_dir, model_provider=ReviewFixtureProvider()),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
