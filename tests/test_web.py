from fastapi.testclient import TestClient

from hris_import.pipeline import MAX_UPLOAD_BYTES
from hris_import.web import app

client=TestClient(app)

CSV=(
    "employee_id,employee_name,email,manager_id,manager_email,department\n"
    "E1,Alice,alice@co.com,,,Eng\n"
    "E2,Bob,bob@co.com,E404,,Eng\n"
)


def test_index_renders_upload_form():
    response=client.get("/")

    assert response.status_code==200
    assert 'action="/upload"' in response.text


def test_upload_renders_summary_and_issue_codes():
    response=client.post("/upload",files={"file":("org.csv",CSV,"text/csv")})

    assert response.status_code==200
    assert "Accepted employees: 2" in response.text
    assert "MANAGER_NOT_FOUND" in response.text


def test_oversized_upload_is_rejected():
    response=client.post("/upload",files={"file":("big.csv",b"x"*(MAX_UPLOAD_BYTES+10),"text/csv")})

    assert response.status_code==200
    assert "FILE_TOO_LARGE" in response.text
