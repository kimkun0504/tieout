import io
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tieout.api import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def upload(client, path, **form):
    with open(path, "rb") as f:
        return client.post("/api/jobs", files={"file": (path.name, f)}, data=form)


def test_health_and_fields(client):
    assert client.get("/api/health").json()["status"] == "ok"
    names = [f["name"] for f in client.get("/api/fields").json()]
    assert "current_rent" in names and "charge_code" in names


def test_upload_returns_full_result(client, flat_csv):
    r = upload(client, flat_csv, as_of="2026-11-01")
    assert r.status_code == 201
    body = r.json()
    assert body["job"]["filename"] == "flat_export.csv"
    assert body["result"]["ok"] is False
    assert body["result"]["summary"]["units"] == 5
    assert "lease_expirations" in body["result"]["metrics"]
    assert [j["id"] for j in client.get("/api/jobs").json()] == [body["job"]["id"]]


def test_upload_rejects_bad_files(client, tmp_path):
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    assert client.post("/api/jobs", files={"file": ("x.exe", exe.read_bytes())}).status_code == 415
    assert client.post("/api/jobs", files={"file": ("e.csv", b"")}).status_code == 422
    junk = client.post("/api/jobs", files={"file": ("j.csv", b"hello\nworld\n")})
    assert junk.status_code == 422 and "Could not read" in junk.json()["detail"]
    broken = client.post("/api/jobs", files={"file": ("b.xlsx", b"not a zip")})
    assert broken.status_code == 422
    assert client.get("/api/jobs").json() == []  # failed uploads leave nothing behind


def test_upload_size_limit(client, monkeypatch):
    import tieout.store as store

    monkeypatch.setattr(store, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/jobs", files={"file": ("big.csv", b"Unit,Rent\n101,1000\n")})
    assert r.status_code == 413


def test_unknown_and_malformed_job_ids(client):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/jobs/not-a-job").status_code == 404


def test_correction_flow_and_audit(client, flat_csv):
    job = upload(client, flat_csv).json()["job"]["id"]
    bad = client.post(f"/api/jobs/{job}/corrections", json={"source_row": 6, "field": "current_rent", "value": "abc", "reason": "x"})
    assert bad.status_code == 422
    r = client.post(
        f"/api/jobs/{job}/corrections",
        json={"source_row": 6, "field": "current_rent", "value": "1625", "reason": "Rent increase"},
        headers={"X-Tieout-User": "kun"},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert "total_does_not_tie_out" not in [i["rule"] for i in result["issues"] if not i["acknowledgment"]]
    row = next(x for x in result["rows"] if x["source_row"] == 6)
    assert row["fields"]["current_rent"]["value"] == "1625.00"
    assert row["fields"]["current_rent"]["original"] == "1575.00"
    assert result["review"]["audit"][-1]["author"] == "kun"

    r = client.delete(f"/api/jobs/{job}/corrections", params={"source_row": 6, "field": "current_rent"})
    assert r.status_code == 200 and r.json()["result"]["review"]["corrections"] == []
    assert client.delete(f"/api/jobs/{job}/corrections", params={"source_row": 6, "field": "current_rent"}).status_code == 404


def test_acknowledge_and_mapping(client, flat_csv):
    job = upload(client, flat_csv).json()["job"]["id"]
    result = client.get(f"/api/jobs/{job}").json()["result"]
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    for i in errors:
        r = client.post(f"/api/jobs/{job}/acknowledgments", json={"issue_id": i["id"], "note": "known"})
        assert r.status_code == 200
    assert r.json()["result"]["ok"] is True
    assert client.get("/api/jobs").json()[0]["last_ok"] is True

    r = client.put(f"/api/jobs/{job}/mapping", json={"header": "Past Due", "field": "other_charges"})
    assert {m["header"]: m["method"] for m in r.json()["result"]["mappings"]}["Past Due"] == "override"
    r = client.put(f"/api/jobs/{job}/mapping", json={"header": "Past Due", "field": "nonsense"})
    assert r.status_code == 422
    r = client.post(f"/api/jobs/{job}/mapping/reset", json={"header": "Past Due", "field": None})
    assert {m["header"]: m["field"] for m in r.json()["result"]["mappings"]}["Past Due"] is None


def test_source_and_exports(client, stacked_xlsx):
    job = upload(client, stacked_xlsx).json()["job"]["id"]
    src = client.get(f"/api/jobs/{job}/source").json()
    assert src["rows"][7][5] == "$1,425.00"  # F8, as in the original
    assert [4, 7, 4, 8] in src["merges"]

    for fmt, ctype in [("csv", "text/csv"), ("xlsx", "spreadsheetml"), ("json", "application/json"), ("issues", "text/csv"), ("report", "markdown")]:
        r = client.get(f"/api/jobs/{job}/export/{fmt}")
        assert r.status_code == 200 and ctype in r.headers["content-type"]
        assert "maple_court" in r.headers["content-disposition"]
    assert json.loads(client.get(f"/api/jobs/{job}/export/json").content)["ok"] is True
    assert client.get(f"/api/jobs/{job}/export/pdf").status_code == 422

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(client.get(f"/api/jobs/{job}/export/xlsx").content))
    assert wb.sheetnames == ["Rent Roll", "Issues", "Summary"]


def test_settings_and_templates(client, flat_csv, tmp_path):
    job = upload(client, flat_csv).json()["job"]["id"]
    r = client.put(f"/api/jobs/{job}/settings", json={"as_of": "2026-11-01"})
    assert r.json()["job"]["as_of"] == "2026-11-01"
    assert client.post(f"/api/jobs/{job}/template", json={"name": "flat"}).status_code == 201
    assert any((tmp_path / "data" / "templates").iterdir())


def test_delete(client, flat_csv):
    job = upload(client, flat_csv).json()["job"]["id"]
    assert client.delete(f"/api/jobs/{job}").status_code == 204
    assert client.get(f"/api/jobs/{job}").status_code == 404
