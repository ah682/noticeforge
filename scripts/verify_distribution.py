"""Exercise an installed wheel outside the checkout, without model downloads.

Run with: uv run --isolated --no-project --with ./dist/noticeforge-0.1.1-py3-none-any.whl
          python scripts/verify_distribution.py
"""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import noticeforge
from noticeforge.exporters import export_smartpcn, validate_xml
from noticeforge.repository import Repository


def main() -> None:
    checkout = Path(__file__).resolve().parents[1]
    package = Path(noticeforge.__file__).resolve().parent
    if package == checkout / "noticeforge":
        raise SystemExit("Run this check with an installed wheel, not the editable source package.")

    with TemporaryDirectory(prefix="noticeforge-wheel-") as directory:
        work = Path(directory)
        for command in ("seed", "evaluate", "smoke"):
            result = subprocess.run(
                [sys.executable, "-m", "noticeforge.cli", command],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode:
                raise SystemExit(f"Installed {command} failed:\n{result.stderr}")

        records = Repository(work / "var").all_notices()
        assert len(records) == 5, "Installed demo must seed all five owned notices"
        site_change = next(
            record for record in records if record.metadata.notice_id.value == "AST-PCN-2026-052"
        )
        xml = export_smartpcn(site_change)
        validate_xml(xml)
        evaluation = json.loads((work / "reports/evaluation.json").read_text())
        assert evaluation["metrics"]["cases"] == 8, "Installed evaluation must run all owned cases"
        assert (work / "reports/cpu-smoke/checkpoint_manifest.json").is_file()
        for asset in ("index.html", "app.css", "app.js"):
            assert (package / "static" / asset).is_file(), f"Missing UI asset: {asset}"

    print(
        "Installed wheel passed: five demo notices, eight evaluation cases, CPU checkpoint, XSD export and UI assets."
    )


if __name__ == "__main__":
    main()
