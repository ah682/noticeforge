"""Canonical v1 records. Untrusted inputs cannot extend the schema."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReviewStatus = Literal["supported", "review_required", "accepted", "corrected"]
DateKind = Literal[
    "last_buy",
    "last_delivery",
    "effective_change",
    "sample_availability",
    "acknowledgment",
    "issue_date",
    "revision_date",
    "end_of_production",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Evidence(StrictModel):
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str
    bbox: tuple[float, float, float, float] | None = None
    method: str = "text"

    @model_validator(mode="after")
    def ordered_offsets(self):
        if self.end < self.start:
            raise ValueError("Evidence end must be after start")
        return self


class TextLine(StrictModel):
    text: str
    start: int
    end: int
    bbox: tuple[float, float, float, float] | None = None


class TableCell(StrictModel):
    text: str
    bbox: tuple[float, float, float, float] | None = None


class SourcePage(StrictModel):
    number: int
    text: str
    width: float | None = None
    height: float | None = None
    method: str = "text"
    lines: list[TextLine] = Field(default_factory=list)
    tables: list[list[list[TableCell]]] = Field(default_factory=list)


class Document(StrictModel):
    sha256: str
    filename: str
    media_type: str
    byte_size: int
    pages: list[SourcePage]
    expected_pages: int | None = None
    complete: bool = True
    warnings: list[str] = Field(default_factory=list)
    coordinate_system: str = "PDF points, top-left origin; zero-based Unicode offsets within each page"


class CriticalValue(StrictModel):
    value: str | None = None
    raw: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    review_status: ReviewStatus = "supported"
    method: str = "rules-v1"
    reason: str | None = None
    model_run_id: str | None = None
    model_candidate_index: int | None = Field(default=None, ge=0)


class DateValue(CriticalValue):
    kind: DateKind
    qualifier: Literal["exact", "tentative", "ambiguous", "inventory_limited", "missing"] = "exact"


class Replacement(StrictModel):
    part_number: CriticalValue
    compatibility: Literal["not_assessed"] = "not_assessed"


class PartRecord(StrictModel):
    id: str
    raw_identifier: CriticalValue
    normalized_identifier: str
    manufacturer: CriticalValue
    group: str
    item_name: CriticalValue = Field(default_factory=CriticalValue)
    item_category: CriticalValue = Field(default_factory=CriticalValue)
    exclusions: list[CriticalValue] = Field(default_factory=list)
    change_categories: list[CriticalValue] = Field(default_factory=list)
    dates: list[DateValue] = Field(default_factory=list)
    exceptions: list[CriticalValue] = Field(default_factory=list)
    replacement_suggestions: list[Replacement] = Field(default_factory=list)
    review_status: ReviewStatus = "supported"


class Contact(StrictModel):
    contact_type: CriticalValue = Field(default_factory=CriticalValue)
    company: CriticalValue = Field(default_factory=CriticalValue)
    email: CriticalValue = Field(default_factory=CriticalValue)
    street: CriticalValue = Field(default_factory=CriticalValue)
    zip_code: CriticalValue = Field(default_factory=CriticalValue)
    city: CriticalValue = Field(default_factory=CriticalValue)
    country: CriticalValue = Field(default_factory=CriticalValue)


class NoticeMetadata(StrictModel):
    notice_id: CriticalValue
    supplier: CriticalValue
    notice_type: CriticalValue
    title: CriticalValue
    issue_date: DateValue
    revision: CriticalValue = Field(default_factory=CriticalValue)
    revision_date: DateValue = Field(
        default_factory=lambda: DateValue(kind="revision_date", qualifier="missing")
    )
    contact: Contact = Field(default_factory=Contact)
    change_title: CriticalValue = Field(default_factory=CriticalValue)
    change_detail: CriticalValue = Field(default_factory=CriticalValue)


class RevisionRelationship(StrictModel):
    kind: Literal["supersedes", "cancels"]
    target_notice_id: CriticalValue
    parts: list[str] = Field(default_factory=list)
    scope: Literal["subset", "all", "unknown"]
    evidence: list[Evidence] = Field(default_factory=list)
    review_status: ReviewStatus = "supported"


class Finding(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    part_ids: list[str] = Field(default_factory=list)
    field_path: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ModelDecision(StrictModel):
    run_id: str
    candidate_index: int = Field(ge=0)
    action: Literal["accept", "reject"]
    provider: str
    model: str
    revision: str | None = None
    configuration_sha256: str
    input_sha256: str
    output_sha256: str | None = None
    context_truncated: bool = False
    input_characters: int = Field(default=0, ge=0)
    included_characters: int = Field(default=0, ge=0)
    reviewer: str
    reason: str
    decided_at: str
    field_paths: list[str] = Field(default_factory=list)


class NoticeRecord(StrictModel):
    id: str
    schema_version: Literal["1.0"] = "1.0"
    metadata: NoticeMetadata
    document: Document
    parts: list[PartRecord]
    relationships: list[RevisionRelationship] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    mode: str = "deterministic-rules"
    compiler_version: str = "0.1.1"
    created_at: str = Field(default_factory=now_iso)
    status: Literal["supported", "review_required", "incomplete", "reviewed"] = "supported"
    version: int = 1
    provenance: Literal["synthetic", "user_supplied"] = "user_supplied"
    model_decisions: list[ModelDecision] = Field(default_factory=list)


class ReviewRequest(StrictModel):
    field_path: str = Field(max_length=300)
    action: Literal["accept", "correct"]
    value: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=3, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    evidence: Evidence | None = None


class ModelRunRequest(StrictModel):
    expected_version: int = Field(ge=1)


class ModelDecisionRequest(StrictModel):
    candidate_index: int = Field(ge=0, le=255)
    action: Literal["accept", "reject"]
    reason: str = Field(min_length=3, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    target_part_id: str | None = Field(default=None, max_length=100)
    replace_date_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def meaningful_attribution(self):
        if len(self.reason.strip()) < 3 or not self.reviewer.strip():
            raise ValueError("Provide a reviewer and a meaningful decision reason")
        return self


class BOMRow(StrictModel):
    part_number: str = Field(min_length=1, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)


class BOMRequest(StrictModel):
    rows: list[BOMRow] = Field(max_length=10000)
