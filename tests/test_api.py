import io
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from tieout.api import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data", allowed_hosts=["testserver", "localhost"]))


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
    bad = client.post(
        f"/api/jobs/{job}/corrections", json={"source_row": 6, "field": "current_rent", "value": "abc", "reason": "x"}
    )
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
    assert (
        client.delete(f"/api/jobs/{job}/corrections", params={"source_row": 6, "field": "current_rent"}).status_code
        == 404
    )


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

    for fmt, ctype in [
        ("csv", "text/csv"),
        ("xlsx", "spreadsheetml"),
        ("json", "application/json"),
        ("issues", "text/csv"),
        ("report", "markdown"),
    ]:
        r = client.get(f"/api/jobs/{job}/export/{fmt}")
        assert r.status_code == 200 and ctype in r.headers["content-type"]
        assert "maple_court" in r.headers["content-disposition"]
    assert json.loads(client.get(f"/api/jobs/{job}/export/json").content)["ok"] is True
    assert client.get(f"/api/jobs/{job}/export/pdf").status_code == 422

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(client.get(f"/api/jobs/{job}/export/xlsx").content))
    assert wb.sheetnames == ["Rent Roll", "Issues", "Summary", "Fields"]


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


def test_provenance_uses_the_uploaded_file_name(client, flat_csv):
    result = upload(client, flat_csv).json()["result"]
    assert result["source"]["file"] == "flat_export.csv"
    assert result["source"]["sheet"] == "flat_export"
    assert result["rows"][0]["fields"]["unit"]["source"]["file"] == "flat_export.csv"


def test_switching_to_an_unreadable_sheet_changes_nothing(client, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Notes"
    wb.active.append(["Prepared by accounting"])
    rr = wb.create_sheet("Rent Roll")
    for row in [["Unit", "Tenant", "Rent"], ["101", "A", 1000], ["102", "B", 1100]]:
        rr.append(row)
    path = tmp_path / "two_sheets.xlsx"
    wb.save(path)

    body = upload(client, path).json()
    job = body["job"]["id"]
    assert body["result"]["source"]["sheet"] == "Rent Roll"  # the fullest sheet is picked
    assert body["result"]["source"]["sheets"] == ["Notes", "Rent Roll"]

    r = client.put(f"/api/jobs/{job}/settings", json={"sheet": "Notes"})
    assert r.status_code == 422 and "Can't use that sheet" in r.json()["detail"]
    after = client.get(f"/api/jobs/{job}")
    assert after.status_code == 200 and after.json()["result"]["source"]["sheet"] == "Rent Roll"


def test_jsonl_export_with_redaction(client, stacked_xlsx):
    job = upload(client, stacked_xlsx).json()["job"]["id"]
    plain = client.get(f"/api/jobs/{job}/export/jsonl")
    assert plain.status_code == 200 and "ndjson" in plain.headers["content-type"]
    lines = [json.loads(x) for x in plain.text.splitlines()]
    assert lines[0]["id"] == "maple_court.xlsx#row-8"
    assert "Garcia" in plain.text
    redacted = client.get(f"/api/jobs/{job}/export/jsonl", params={"redact_tenants": True})
    assert "Garcia" not in redacted.text


def test_security_headers_and_request_id(client):
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Request-ID"] == "abc123"
    assert len(client.get("/api/health").headers["X-Request-ID"]) == 12


def test_t12_upload_is_detected_and_checked(client, tmp_path):
    from samples import make_t12_xlsx

    body = upload(client, make_t12_xlsx(tmp_path / "maple_t12.xlsx", noi_off_by=250)).json()
    assert body["result"]["document_type"] == "t12"
    assert body["result"]["ok"] is False
    assert [i["rule"] for i in body["result"]["issues"] if i["severity"] == "error"] == ["t12_noi_mismatch"]
    job = body["job"]
    assert job["document_type"] == "t12" and job["last_summary"]["period"] == "Nov 2025 to Oct 2026"

    jid = job["id"]
    r = client.post(
        f"/api/jobs/{jid}/corrections", json={"source_row": 6, "field": "current_rent", "value": "1", "reason": "x"}
    )
    assert r.status_code == 409
    for fmt in ("json", "csv", "xlsx", "report"):
        r = client.get(f"/api/jobs/{jid}/export/{fmt}")
        assert r.status_code == 200, fmt
        assert "maple_t12" in r.headers["content-disposition"]
    assert client.get(f"/api/jobs/{jid}/export/jsonl").status_code == 422
    tidy = client.get(f"/api/jobs/{jid}/export/csv").text.splitlines()
    assert tidy[0] == "month,section,category,code,line_item,amount,source_cell,source_row"
    assert len(tidy) == 1 + 17 * 12


def test_rent_roll_payload_names_its_type(client, flat_csv):
    assert upload(client, flat_csv).json()["result"]["document_type"] == "rent_roll"


def test_compare_endpoint(client, tmp_path, flat_csv):
    from samples import make_t12_xlsx

    rr = upload(client, flat_csv, as_of="2026-11-01").json()["job"]["id"]
    t12 = upload(client, make_t12_xlsx(tmp_path / "t.xlsx")).json()["job"]["id"]
    r = client.get("/api/compare", params={"rent_roll": rr, "t12": t12})
    assert r.status_code == 200
    body = r.json()
    assert body["t12"]["last_month"] == "2026-10"
    assert {c["metric"] for c in body["checks"]} == {"gross_potential_rent", "rent_in_place", "economic_occupancy"}
    assert client.get("/api/compare", params={"rent_roll": t12, "t12": rr}).status_code == 422


def test_dns_rebinding_host_is_refused(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"host": "localhost:8000"}).status_code == 200


def test_cross_site_writes_are_refused(client, flat_csv):
    with open(flat_csv, "rb") as f:
        r = client.post("/api/jobs", files={"file": ("x.csv", f)}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/api/jobs").json() == []
    with open(flat_csv, "rb") as f:  # same-origin browser request
        assert (
            client.post("/api/jobs", files={"file": ("x.csv", f)}, headers={"origin": "http://testserver"}).status_code
            == 201
        )
    # reads are unaffected
    assert client.get("/api/health", headers={"origin": "https://evil.example"}).status_code == 200


def test_default_allowed_hosts(monkeypatch):
    from tieout.api import allowed_hosts_from_env

    monkeypatch.delenv("TIEOUT_ALLOWED_HOSTS", raising=False)
    assert allowed_hosts_from_env() == ["localhost", "127.0.0.1", "[::1]"]
    monkeypatch.setenv("TIEOUT_ALLOWED_HOSTS", "tieout.internal, localhost")
    assert allowed_hosts_from_env() == ["tieout.internal", "localhost"]


def test_t12_issues_can_be_accepted_with_a_note(client, tmp_path):
    from samples import make_t12_xlsx

    body = upload(client, make_t12_xlsx(tmp_path / "t.xlsx", noi_off_by=250)).json()
    jid, [issue] = body["job"]["id"], [i for i in body["result"]["issues"] if i["severity"] == "error"]
    r = client.post(
        f"/api/jobs/{jid}/acknowledgments", json={"issue_id": issue["id"], "note": "Accrual reversal in Dec"}
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["ok"] is True and result["summary"]["acknowledged"] == 1
    assert result["review"]["audit"][-1]["action"] == "acknowledge"
    assert client.get("/api/jobs").json()[0]["last_ok"] is True
    r = client.delete(f"/api/jobs/{jid}/acknowledgments/{issue['id']}")
    assert r.json()["result"]["ok"] is False


def test_exports_keep_non_latin_file_names(client, stacked_xlsx):
    from urllib.parse import unquote

    job = client.post("/api/jobs", files={"file": ("李 roll (Oct).xlsx", stacked_xlsx.read_bytes())}).json()["job"]
    for fmt in ("csv", "report", "bundle"):
        r = client.get(f"/api/jobs/{job['id']}/export/{fmt}")
        assert r.status_code == 200, r.text
        cd = r.headers["content-disposition"]
        cd.encode("latin-1")  # header values must be Latin-1
        assert unquote(cd.split("filename*=UTF-8''")[1]).startswith("李 roll (Oct).")


def test_bundle_zips_every_output(client, stacked_xlsx):
    import zipfile

    job = client.post("/api/jobs", files={"file": ("maple.xlsx", stacked_xlsx.read_bytes())}).json()["job"]
    r = client.get(f"/api/jobs/{job['id']}/export/bundle")
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    suffixes = (".clean.csv", ".clean.json", ".issues.csv", ".report.md", ".clean.xlsx", ".records.jsonl")
    assert sorted(z.namelist()) == sorted(f"maple/maple{s}" for s in (*suffixes, ".datapackage.json"))
    pkg = json.loads(z.read("maple/maple.datapackage.json"))
    assert pkg["resources"][0]["path"] == "maple.clean.csv"
