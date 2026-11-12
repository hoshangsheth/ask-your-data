"""
Upload flow end to end over HTTP: upload a file, list it, read its schema, ask a question about
it (scripted model), and delete it. Also limits and error codes.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.llm import SQLDraft, Summary
from tests import sample_files as files
from tests.fakes import FakeLLM

REGION_TOTALS = SQLDraft(True, "SELECT region, SUM(amount) AS total_amount FROM sales GROUP BY region", "Totals.")


def upload(client, data: bytes, filename: str):
    return client.post("/api/datasets", files={"file": (filename, data, "application/octet-stream")})


def test_upload_list_schema_ask_delete(settings):
    llm = FakeLLM([REGION_TOTALS], Summary("South leads.", "bar", "region", "total_amount"))
    with TestClient(create_app(settings, llm)) as c:
        r = upload(c, files.csv(), "sales.csv")
        assert r.status_code == 201, r.text
        ds = r.json()
        assert ds["kind"] == "upload" and ds["tables"] == [{"name": "sales", "rows": 6, "columns": 4}]
        assert ds["suggestions"]

        listed = c.get("/api/datasets").json()
        assert [d["id"] for d in listed][:2] == ["demo", ds["id"]]

        schema = c.get(f"/api/schema?dataset={ds['id']}").json()
        assert schema["tables"]["sales"]["row_count"] == 6

        answer = c.post("/api/ask", json={"question": "Total amount by region?", "dataset_id": ds["id"]}).json()
        assert answer["status"] == "ok" and answer["dataset_id"] == ds["id"] and answer["currency"] is None
        assert dict(answer["rows"]) == {"East": 800, "North": 2150, "South": 5600, "West": 1750}
        prompt = llm.calls[0]["schema"]
        assert "TABLE sales" in prompt and "orders" not in prompt  # the agent saw only this dataset

        assert c.delete(f"/api/datasets/{ds['id']}").status_code == 204
        assert c.get(f"/api/datasets/{ds['id']}").status_code == 404
        assert c.post("/api/ask", json={"question": "Total amount?", "dataset_id": ds["id"]}).status_code == 404


def test_uploaded_dataset_cannot_read_demo_tables(settings):
    sneaky = SQLDraft(True, "SELECT COUNT(*) FROM orders", "x")
    with TestClient(create_app(settings, FakeLLM([sneaky] * 3))) as c:
        ds = upload(c, files.csv(), "sales.csv").json()
        out = c.post("/api/ask", json={"question": "count orders", "dataset_id": ds["id"]}).json()
        assert out["status"] == "failed" and "unknown table" in out["answer"]


def test_demo_answers_keep_inr(settings):
    demo = SQLDraft(True, "SELECT region, COUNT(*) AS customers FROM customers GROUP BY region", "x")
    with TestClient(create_app(settings, FakeLLM([demo]))) as c:
        assert c.post("/api/ask", json={"question": "customers by region"}).json()["currency"] == "INR"


def test_upload_errors(settings):
    s = settings.model_copy(update={"max_upload_mb": 1})
    with TestClient(create_app(s, FakeLLM([]))) as c:
        assert upload(c, b"x", "malware.exe").status_code == 415
        assert upload(c, b"", "empty.csv").status_code == 400
        assert upload(c, b"a,b\n" + b"1,2\n" * 400_000, "big.csv").status_code == 413
        assert upload(c, b"{broken", "bad.json").status_code == 422
        assert c.delete("/api/datasets/demo").status_code == 400
        assert c.delete("/api/datasets/../../etc").status_code in (404, 405)
        assert c.get("/api/datasets/not-an-id").status_code == 404


def test_formats_endpoint(settings):
    with TestClient(create_app(settings, FakeLLM([]))) as c:
        body = c.get("/api/formats").json()
        assert ".xlsx" in body["extensions"] and body["max_upload_mb"] == settings.max_upload_mb
        assert body["part_mb"] == settings.upload_part_mb


# ---- multi-part uploads (what the browser uses) ------------------------------------------------
def multipart_upload(client, data: bytes, filename: str):
    start = client.post("/api/uploads", json={"filename": filename, "size": len(data)})
    assert start.status_code == 201, start.text
    s = start.json()
    for i in range(s["parts"]):
        part = data[i * s["part_bytes"] : (i + 1) * s["part_bytes"]]
        assert client.put(f"/api/uploads/{s['upload_id']}/parts/{i}", content=part).status_code == 204
    return s, client.post(f"/api/uploads/{s['upload_id']}/complete", json={"filename": filename, "parts": s["parts"]})


def test_multipart_upload_joins_parts(settings):
    s = settings.model_copy(update={"upload_part_mb": 1})
    rows = "".join(f"{i},{['North', 'South'][i % 2]},{i * 10}\n" for i in range(150_000))
    data = ("id,region,amount\n" + rows).encode()  # ~2.5 MB -> 3 parts of 1 MB
    with TestClient(create_app(s, FakeLLM([]))) as c:
        started, done = multipart_upload(c, data, "big sales.csv")
        assert started["parts"] == 3
        assert done.status_code == 201, done.text
        ds = done.json()
        assert ds["tables"] == [{"name": "big_sales", "rows": 150_000, "columns": 3}]
        assert ds["size_bytes"] == len(data)
        # Staged parts are removed once the dataset exists.
        assert not (Path(s.uploads_dir) / "staging" / started["upload_id"]).exists()
        assert c.delete(f"/api/datasets/{ds['id']}").status_code == 204


def test_multipart_upload_errors(settings):
    s = settings.model_copy(update={"max_upload_mb": 2, "upload_part_mb": 1})
    with TestClient(create_app(s, FakeLLM([]))) as c:
        assert c.post("/api/uploads", json={"filename": "x.exe", "size": 10}).status_code == 415
        assert c.post("/api/uploads", json={"filename": "x.csv", "size": 0}).status_code == 400
        assert c.post("/api/uploads", json={"filename": "x.csv", "size": 3 * 1024 * 1024}).status_code == 413

        uid = c.post("/api/uploads", json={"filename": "x.csv", "size": 10}).json()["upload_id"]
        assert c.put(f"/api/uploads/{uid}/parts/0", content=b"x" * (1024 * 1024 + 1)).status_code == 413
        assert c.put(f"/api/uploads/{uid}/parts/-1", content=b"a").status_code == 400
        assert c.put("/api/uploads/not-an-id/parts/0", content=b"a").status_code == 404
        # Part 1 of 2 never arrived.
        assert c.put(f"/api/uploads/{uid}/parts/0", content=b"a,b\n1,2\n").status_code == 204
        missing = c.post(f"/api/uploads/{uid}/complete", json={"filename": "x.csv", "parts": 2})
        assert missing.status_code == 409 and "missing" in missing.json()["detail"]


def test_health_reports_storage(settings):
    with TestClient(create_app(settings, FakeLLM([]))) as c:
        storage = c.get("/api/health").json()["storage"]
        assert storage["files"] == "local" and storage["datasets"] in ("sqlite-files", "postgres")
