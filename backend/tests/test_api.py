"""HTTP validation paths. None of these reach the pipeline, so no model loads."""

import pytest
from fastapi.testclient import TestClient

from api_app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_rejects_non_pdf_filename(client):
    r = client.post("/api/analyze", files={"resume": ("cv.txt", b"%PDF-1.4", "text/plain")},
                    data={"jd_text": "Python"})
    assert r.status_code == 400


def test_rejects_fake_pdf(client):
    r = client.post("/api/analyze", files={"resume": ("cv.pdf", b"hello", "application/pdf")},
                    data={"jd_text": "Python"})
    assert r.status_code == 400
    assert "not a valid PDF" in r.json()["detail"]


def test_rejects_blank_job_description(client):
    r = client.post("/api/analyze", files={"resume": ("cv.pdf", b"%PDF-1.4", "application/pdf")},
                    data={"jd_text": "   "})
    assert r.status_code in (400, 422)


@pytest.mark.parametrize("job_id", ["zzz", "0123456789ab", "../../etc/passwd"])
def test_download_unknown_job(client, job_id):
    assert client.get(f"/api/download/{job_id}").status_code == 404
