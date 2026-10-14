"""Public CPU baseline entry point. Model candidates never bypass canonical checks."""

from noticeforge.extraction import extract_notice
from noticeforge.ingest import extract_document
from noticeforge.models import NoticeRecord
from noticeforge.validation import validate_record


def compile_notice(data: bytes, filename: str, expected_pages: int | None = None) -> NoticeRecord:
    return validate_record(extract_notice(extract_document(data, filename, expected_pages)))
