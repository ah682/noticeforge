from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from noticeforge.api import create_app
from noticeforge.bom import match_bom
from noticeforge.cli import seed
from noticeforge.models import BOMRow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    seed(tmp_path)
    return TestClient(create_app(tmp_path), base_url="http://127.0.0.1")


def named(client, prefix):
    notices = client.get("/api/notices").json()["notices"]
    selected = next(r for r in notices if r["filename"].startswith(prefix))
    return client.get("/api/notices/" + selected["id"]).json()


def test_seed_upload_export_and_replay_are_persistent(client):
    assert client.get("/api/health").json()["automatic_external_calls"] is False
    record = named(client, "aster-discontinuation")
    data = (ROOT / "fixtures/development/aster-discontinuation.pdf").read_bytes()
    uploaded = client.post("/api/notices", files={"file": ("again.pdf", data, "application/pdf")})
    assert uploaded.status_code == 201
    assert uploaded.json()["id"] == record["id"]
    exported = client.get(f"/api/notices/{record['id']}/export")
    assert exported.json()["parts"][0]["raw_identifier"]["value"] == "00128-Q1"
    assert client.get(f"/api/notices/{record['id']}/pages/1/image").content.startswith(b"\x89PNG")


def test_correction_audit_original_and_stale_write(client):
    record = named(client, "borealis-review")
    path = f"/api/notices/{record['id']}/reviews"
    payload = {
        "field_path": "parts.0.dates.0",
        "action": "accept",
        "reason": "Checked source",
        "reviewer": "Engineer",
        "expected_version": record["version"],
    }
    assert client.post(path, json=payload).status_code == 422
    payload.update(
        action="correct", value="2027-04-03", reason="Supplier date convention confirmed: day/month/year"
    )
    response = client.post(path, json=payload)
    assert response.status_code == 200
    corrected = response.json()["parts"][0]["dates"][0]
    assert corrected["value"] == "2027-04-03"
    assert corrected["raw"] == "03/04/2027"
    assert corrected["review_status"] == "corrected"
    assert client.post(path, json=payload).status_code == 409
    audit = client.get(f"/api/notices/{record['id']}/audit").json()["events"]
    assert audit[0]["before"]["value"] is None
    assert audit[0]["after"]["value"] == "2027-04-03"
    assert client.app.state.repo.original(record["id"]).parts[0].dates[0].value is None
    assert client.app.state.repo.get(record["id"]).version == 2


def test_review_rejects_arbitrary_schema_change_and_bad_evidence(client):
    record = named(client, "borealis-review")
    payload = {
        "field_path": "schema_version",
        "action": "correct",
        "value": "9",
        "reason": "Test case",
        "reviewer": "Engineer",
        "expected_version": 1,
    }
    url = f"/api/notices/{record['id']}/reviews"
    assert client.post(url, json=payload).status_code == 422
    payload.update(
        field_path="parts.0.dates.0", value="2027-04-03", evidence={"page": 999, "start": 0, "end": 3}
    )
    assert client.post(url, json=payload).status_code == 422


def test_subset_revision_never_overwrites_other_parts(client):
    old = named(client, "aster-discontinuation")
    history = client.get(f"/api/notices/{old['id']}/history").json()
    assert history["incoming"][0]["affected_parts"] == ["NX-4100-B"]
    assert len(history["incoming"][0]["unaffected_parts"]) == 5
    assert len(client.get(f"/api/notices/{old['id']}").json()["parts"]) == 6


def test_literal_manufacturer_matching_misses_and_ambiguity(client):
    record = named(client, "aster-discontinuation")
    response = client.post(
        f"/api/notices/{record['id']}/bom",
        json={
            "rows": [
                {"part_number": "00128-Q1", "manufacturer": "Aster Semiconductor"},
                {"part_number": "00128-Q1", "manufacturer": "Other Supplier"},
                {"part_number": "128-Q1", "manufacturer": "Aster Semiconductor"},
                {"part_number": "00128-Q1"},
            ]
        },
    )
    assert [row["status"] for row in response.json()["matches"]] == [
        "literal_match",
        "unmatched",
        "unmatched",
        "ambiguous",
    ]
    canonical = client.app.state.repo.get(record["id"])
    canonical.parts[0].raw_identifier.review_status = "review_required"
    result = match_bom(canonical, [BOMRow(part_number="00128-Q1", manufacturer="Aster Semiconductor")])
    assert result[0]["status"] == "ambiguous"


def test_exports_distinguish_json_and_actual_schema_support(client):
    good = named(client, "aster-site-transfer")
    xml = client.get(f"/api/notices/{good['id']}/export?format=smartpcn")
    assert xml.status_code == 200, xml.text
    from noticeforge.exporters import validate_xml

    validate_xml(xml.content)
    review = named(client, "borealis-review")
    assert client.get(f"/api/notices/{review['id']}/export?format=smartpcn").status_code == 422
    assert client.get(f"/api/notices/{review['id']}/export?format=json").status_code == 200


def test_invalid_upload_and_cross_origin_write_fail(client):
    assert client.post("/api/notices", files={"file": ("file.pdf", b"bad")}).status_code == 400
    assert (
        client.post(
            "/api/notices", headers={"Origin": "https://evil.example"}, files={"file": ("a.txt", b"x")}
        ).status_code
        == 403
    )
    assert client.get("/api/notices/missing").status_code == 404
