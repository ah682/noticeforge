"""One documented local entry point plus reproducible evaluation commands."""

import argparse
import json
import os
from pathlib import Path

from noticeforge.pipeline import compile_notice
from noticeforge.repository import Repository
from noticeforge.resources import DATA_ROOT


def seed(data_dir: Path):
    repo = Repository(data_dir)
    manifest = json.loads((DATA_ROOT / "fixtures/development/manifest.json").read_text())
    for entry in manifest["documents"]:
        path = DATA_ROOT / "fixtures/development" / entry["path"]
        data = path.read_bytes()
        record = compile_notice(data, path.name)
        record.provenance = "synthetic"
        repo.save(record, data)
    return repo


def main():
    parser = argparse.ArgumentParser(description="NoticeForge local evidence-linked notice compiler")
    parser.add_argument("command", choices=["demo", "seed", "reset", "extract", "evaluate", "smoke"])
    parser.add_argument("input", nargs="?")
    parser.add_argument("--out", default="reports")
    parser.add_argument("--data-dir", default=os.getenv("NOTICEFORGE_DATA_DIR", "var"))
    parser.add_argument("--host", default=os.getenv("NOTICEFORGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NOTICEFORGE_PORT", "8877")))
    args = parser.parse_args()
    root = Path(args.data_dir)
    if args.command in {"demo", "seed", "reset"}:
        if args.command == "reset":
            # Reset is scoped to our one database, never a recursive directory deletion.
            db = root / "noticeforge.sqlite3"
            for path in [db, Path(str(db) + "-wal"), Path(str(db) + "-shm")]:
                path.unlink(missing_ok=True)
        repo = seed(root)
        print(
            f"NoticeForge: {len(repo.all_notices())} local notices; deterministic rules; owned synthetic demo"
        )
        if args.command == "demo":
            import uvicorn

            from noticeforge.api import create_app

            print(f"Open http://{args.host}:{args.port}")
            uvicorn.run(create_app(root), host=args.host, port=args.port, log_level="info")
    elif args.command == "extract":
        if not args.input:
            parser.error("extract requires a PDF or TXT path")
        path = Path(args.input)
        record = compile_notice(path.read_bytes(), path.name)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{path.stem}.json"
        target.write_text(record.model_dump_json(indent=2) + "\n")
        print(f"{target}: {record.status}, {len(record.parts)} parts")
    elif args.command == "evaluate":
        from noticeforge.evaluation import run_evaluation

        result = run_evaluation(Path(args.out))
        print(
            json.dumps(
                {
                    "report": str(Path(args.out) / "evaluation.json"),
                    "metrics": result["metrics"],
                    "p95_extraction_ms": round(result["benchmark"]["p95_extraction_seconds"] * 1000, 3),
                    "purpose": result["purpose"],
                },
                indent=2,
            )
        )
    elif args.command == "smoke":
        from noticeforge.training import run_smoke

        result = run_smoke(Path(args.out) / "cpu-smoke")
        print(
            json.dumps(
                {
                    "report_directory": str(Path(args.out) / "cpu-smoke"),
                    "purpose": "CPU training/checkpoint/load smoke only; not the domain model",
                    "status": "completed",
                    "unexecuted": result.get("unexecuted", []),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
