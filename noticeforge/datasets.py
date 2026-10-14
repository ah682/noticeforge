"""Permission-aware partner imports and reproducible leakage checks.

Public availability is deliberately not a permission. No downloads occur here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    path: str
    source: str
    permission_status: str
    license: str
    supplier: str
    template: str
    family: str
    classification: Literal["synthetic", "real"]
    split: str
    annotation_provenance: str | dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    sha256: str | None = None
    created_at: str | None = None
    transformations: list[str] = Field(default_factory=list)
    permission_reference: str | None = None
    expected_pages: int | None = None
    annotation_path: str | None = None

    @field_validator("id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("document id must be a safe file identifier")
        return value

    @field_validator("supplier", "template", "family", "source", "license")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("manifest attribution fields must not be blank")
        return value


class SpanAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class RelationshipAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_raw: str = Field(min_length=1)
    date_type: Literal[
        "last_buy",
        "last_delivery",
        "effective_change",
        "sample_availability",
        "acknowledgment",
        "end_of_production",
    ]
    date: str | None
    date_text: str
    exception: str | None = None
    review_required: bool = False
    evidence: list[SpanAnnotation] = Field(min_length=1)

    @field_validator("date")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        if value is not None:
            from datetime import date

            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("dates must use YYYY-MM-DD")
        return value


class PartnerAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    annotator: str = Field(min_length=1)
    created_at: str
    parts: list[str]
    relationships: list[RelationshipAnnotation]
    adjudicator: str | None = None
    notes: str = ""


def load_manifest(path: Path) -> tuple[list[DatasetDocument], dict[str, Any]]:
    data = json.loads(path.read_text())
    raw = data if isinstance(data, list) else data.get("documents", data.get("cases", []))
    if not isinstance(raw, list) or not raw:
        raise ValueError("manifest must contain a nonempty documents list")
    entries = [DatasetDocument.model_validate(item) for item in raw]
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError("duplicate document ids")
    return entries, data if isinstance(data, dict) else {}


def resolve_document(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("document path must name a file inside the manifest directory")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("dataset documents are limited to 20 MiB")
    return path


def page_texts(path: Path, *, require_complete: bool = False, expected_pages: int | None = None) -> list[str]:
    """Use precisely the same retained text and offsets as extraction and serving."""
    from .ingest import extract_document

    document = extract_document(path.read_bytes(), path.name, expected_pages)
    if require_complete and not document.complete:
        raise ValueError(
            "incomplete source cannot supply training annotations: " + "; ".join(document.warnings)
        )
    return [page.text for page in document.pages]


def permission_problem(document: DatasetDocument) -> str | None:
    if document.classification == "synthetic":
        if document.permission_status not in {"owned_synthetic", "owned", "authorized", "open_license"}:
            return "synthetic material requires recorded ownership or reuse permission"
    elif document.permission_status not in {"authorized", "open_license", "licensed"}:
        return "public readability does not grant real-data training/evaluation rights"
    elif not document.permission_reference:
        return "real material requires a permission_reference documenting training/evaluation rights"
    if document.license.lower() in {"unknown", "pending", "none", "unspecified"}:
        return "license/authorization terms are missing"
    if not document.annotation_provenance:
        return "annotation provenance is missing"
    return None


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if a == b and a:
        return 1.0
    if min(len(a), len(b)) < 12:
        return 0.0

    def shingles(words: list[str]) -> set[tuple[str, ...]]:
        return {tuple(words[i : i + 5]) for i in range(len(words) - 4)}

    sa, sb = shingles(a), shingles(b)
    jaccard = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
    # Sequence similarity catches short pages with small edits that destroy many
    # 5-word shingles. Cap this quadratic fallback; large pages retain Jaccard.
    sequence = SequenceMatcher(None, a, b, autojunk=True).ratio() if max(len(a), len(b)) <= 2000 else 0.0
    return max(jaccard, sequence)


def audit_manifest(path: Path, *, threshold: float = 0.8, require_holdouts: bool = True) -> dict[str, Any]:
    """Fail closed on permission/hash errors and cross-split groups/near duplicates.

    Comparison is exhaustive and intended for pilot corpora, not millions of pages.
    Threshold is frozen in configuration before final testing; no auto tuning occurs.
    """
    if not 0 < threshold <= 1:
        raise ValueError("near-duplicate threshold must be in (0, 1]")
    entries, metadata = load_manifest(path)
    issues: list[dict[str, Any]] = []
    pages: dict[str, list[str]] = {}
    hashes: dict[str, str] = {}
    for item in entries:
        problem = permission_problem(item)
        if problem:
            issues.append({"code": "permission", "documents": [item.id], "detail": problem})
        try:
            source = resolve_document(path.parent, item.path)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            hashes[item.id] = digest
            if item.sha256 is not None and item.sha256 != digest:
                issues.append({"code": "hash_mismatch", "documents": [item.id]})
            pages[item.id] = page_texts(source)
        except (OSError, ValueError, RuntimeError) as exc:
            issues.append({"code": "unreadable_source", "documents": [item.id], "detail": str(exc)})
    keys = ["family"] + (["supplier", "template"] if require_holdouts else [])
    for key in keys:
        groups: dict[str, list[DatasetDocument]] = defaultdict(list)
        for item in entries:
            groups[str(getattr(item, key)).strip().casefold()].append(item)
        for group, members in groups.items():
            if len({member.split for member in members}) > 1:
                issues.append(
                    {
                        "code": f"{key}_leakage",
                        "group": group,
                        "documents": [m.id for m in members],
                        "splits": sorted({m.split for m in members}),
                    }
                )
    duplicates: list[dict[str, Any]] = []
    for left, right in combinations(entries, 2):
        if left.id not in hashes or right.id not in hashes:
            continue
        matches = []
        for i, a in enumerate(pages.get(left.id, []), 1):
            for j, b in enumerate(pages.get(right.id, []), 1):
                similarity = _similarity(a, b)
                if similarity >= threshold:
                    matches.append({"left_page": i, "right_page": j, "similarity": round(similarity, 6)})
        identical_document = hashes[left.id] == hashes[right.id]
        if matches or identical_document:
            match = {
                "documents": [left.id, right.id],
                "pages": matches,
                "identical_document_sha256": identical_document,
                "cross_split": left.split != right.split,
            }
            duplicates.append(match)
            if match["cross_split"]:
                issues.append({"code": "near_duplicate_leakage", **match})
    return {
        "ok": not issues,
        "documents": len(entries),
        "classification_counts": {
            c: sum(d.classification == c for d in entries) for c in ("synthetic", "real")
        },
        "issues": issues,
        "near_duplicates": duplicates,
        "document_hashes": hashes,
        "method": "max(word 5-shingle Jaccard, token sequence ratio for pages <=2000 tokens); exact normalized equality at any length",
        "threshold": threshold,
        "holdouts": keys,
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "purpose": metadata.get("purpose", "unspecified"),
    }


def assign_splits(path: Path, out_path: Path, *, seed: int = 17, threshold: float = 0.8) -> dict[str, Any]:
    """Group suppliers, templates, families and duplicate pages before assignment."""
    entries, metadata = load_manifest(path)
    audit = audit_manifest(path, threshold=threshold)
    blockers = [
        i for i in audit["issues"] if i["code"] in {"permission", "hash_mismatch", "unreadable_source"}
    ]
    if blockers:
        raise ValueError(f"cannot prepare dataset: {blockers}")
    if path.resolve() == out_path.resolve():
        raise ValueError("prepared manifest must not overwrite the source manifest")
    parent = {entry.id: entry.id for entry in entries}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)

    for key in ("supplier", "template", "family"):
        seen: dict[str, str] = {}
        for item in entries:
            value = str(getattr(item, key)).casefold().strip()
            if value in seen:
                union(item.id, seen[value])
            seen[value] = item.id
    for duplicate in audit["near_duplicates"]:
        union(*duplicate["documents"])
    groups: dict[str, list[str]] = defaultdict(list)
    for item in entries:
        groups[find(item.id)].append(item.id)
    assignments = {}
    for members in groups.values():
        digest = hashlib.sha256(f"{seed}:".encode() + "|".join(sorted(members)).encode()).hexdigest()
        fraction = int(digest[:8], 16) / 2**32
        split = "train" if fraction < 0.7 else "validation" if fraction < 0.85 else "test"
        assignments.update({member: split for member in members})
    result: dict[str, Any] = {
        **metadata,
        "split_seed": seed,
        "split_policy": "connected supplier/template/family/near-duplicate components; SHA256 70/15/15 allocation; no guaranteed split sizes",
        "near_duplicate_threshold": threshold,
        "documents": [],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def contained_copy(source: Path, name: str) -> str:
        if source.is_relative_to(out_path.parent.resolve()):
            return str(source.relative_to(out_path.parent.resolve()))
        destination = out_path.parent / (out_path.stem + ".data") / name
        destination.parent.mkdir(exist_ok=True)
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError("prepared data destination contains a different file")
        if not destination.exists():
            shutil.copyfile(source, destination)
        return str(destination.relative_to(out_path.parent))

    for item in entries:
        serialized = item.model_dump(exclude_none=True)
        source = resolve_document(path.parent, item.path)
        serialized["path"] = contained_copy(source, item.id + source.suffix.lower())
        if item.annotation_path:
            annotation_source = resolve_document(path.parent, item.annotation_path)
            serialized["annotation_path"] = contained_copy(
                annotation_source,
                "annotations-" + hashlib.sha256(annotation_source.read_bytes()).hexdigest()[:16] + ".jsonl",
            )
        serialized["split"] = assignments[item.id]
        serialized["sha256"] = audit["document_hashes"][item.id]
        result["documents"].append(serialized)
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    return {
        "groups": len(groups),
        "splits": {s: sum(v == s for v in assignments.values()) for s in ("train", "validation", "test")},
        "warning": "Small grouped datasets can have empty splits; obtain additional independent groups, never break groups.",
    }


def validate_annotation(annotation: PartnerAnnotation, pages: list[str]) -> None:
    from .providers import _normalized_literal_date

    def exact_part(part: str, text: str) -> bool:
        return re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(part) + r"(?![A-Za-z0-9_.-])", text) is not None

    for part in annotation.parts:
        if not any(exact_part(part, text) for text in pages):
            raise ValueError(f"annotated part {part!r} is absent from source")
    for relation in annotation.relationships:
        if relation.part_raw not in annotation.parts:
            raise ValueError("relationship part is absent from annotated parts")
        quotes = []
        for span in relation.evidence:
            if span.page > len(pages) or pages[span.page - 1][span.start : span.end] != span.quote:
                raise ValueError("annotation evidence does not match exact source offsets")
            quotes.append(span.quote)
        combined = "\n".join(quotes)
        if not exact_part(relation.part_raw, combined) or (
            relation.date_text and relation.date_text not in combined
        ):
            raise ValueError("relationship evidence must include its part and date text")
        if relation.date is not None and _normalized_literal_date(relation.date_text) != relation.date:
            raise ValueError("annotation date must equal an unambiguous literal normalization")
        if relation.exception and relation.exception not in combined:
            raise ValueError("relationship exception must occur in cited evidence")


def import_partner(manifest_path: Path, annotations_path: Path, destination: Path) -> dict[str, Any]:
    """Validate an authorized package before copying. Never overwrites a package."""
    if destination.exists():
        raise ValueError("destination already exists; imports are immutable packages")
    entries, metadata = load_manifest(manifest_path)
    audit = audit_manifest(manifest_path)
    if not audit["ok"]:
        raise ValueError(f"partner data audit failed: {audit['issues']}")
    annotations = [
        PartnerAnnotation.model_validate(json.loads(line))
        for line in annotations_path.read_text().splitlines()
        if line.strip()
    ]
    lookup = {a.document_id: a for a in annotations}
    if len(lookup) != len(annotations) or set(lookup) != {entry.id for entry in entries}:
        raise ValueError("provide exactly one annotation per manifest document")
    for entry in entries:
        validate_annotation(
            lookup[entry.id],
            page_texts(
                resolve_document(manifest_path.parent, entry.path),
                require_complete=True,
                expected_pages=entry.expected_pages,
            ),
        )
    destination.mkdir(parents=True)
    try:
        (destination / "documents").mkdir()
        result = {**metadata, "imported_at": datetime.now(timezone.utc).isoformat(), "documents": []}
        for entry in entries:
            source = resolve_document(manifest_path.parent, entry.path)
            relative = f"documents/{entry.id}{source.suffix.lower()}"
            shutil.copyfile(source, destination / relative)
            value = entry.model_dump(exclude_none=True)
            value.update(
                path=relative, sha256=audit["document_hashes"][entry.id], annotation_path="annotations.jsonl"
            )
            value["annotation_provenance"] = {
                "annotator": lookup[entry.id].annotator,
                "created_at": lookup[entry.id].created_at,
                "adjudicator": lookup[entry.id].adjudicator,
                "source": str(annotations_path.name),
            }
            value["expected"] = {
                "parts": lookup[entry.id].parts,
                "relationships": [r.model_dump() for r in lookup[entry.id].relationships],
            }
            result["documents"].append(value)
        (destination / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
        (destination / "annotations.jsonl").write_text(
            "".join(a.model_dump_json() + "\n" for a in annotations)
        )
        (destination / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"imported": len(entries), "destination": str(destination), "audit_ok": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("manifest", type=Path)
    audit.add_argument("--output", type=Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("manifest", type=Path)
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--seed", type=int, default=17)
    imp = commands.add_parser("import")
    imp.add_argument("manifest", type=Path)
    imp.add_argument("annotations", type=Path)
    imp.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "audit":
        result = audit_manifest(args.manifest)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
    elif args.command == "prepare":
        result = assign_splits(args.manifest, args.output, seed=args.seed)
    else:
        result = import_partner(args.manifest, args.annotations, args.destination)
    print(json.dumps(result, indent=2))
    if result.get("ok") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
