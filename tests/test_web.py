import html
import re

from fastapi.testclient import TestClient

from hris_import.pipeline import MAX_UPLOAD_BYTES, run_import_preview
from hris_import.web import app

client=TestClient(app)

CSV=(
    "employee_id,employee_name,email,manager_id,manager_email,department\n"
    "E1,Alice,alice@co.com,,,Eng\n"
    "E2,Bob,bob@co.com,e1,,Eng\n" #format drift: confident fix to E1
    "E3,Cara,cara@co.com,E404,,Eng\n" #nothing close: manual
)


def upload(text:str=CSV):
    return client.post("/upload",files={"file":("org.csv",text,"text/csv")})


def test_index_renders_upload_form():
    response=client.get("/")

    assert response.status_code==200
    assert 'action="/upload"' in response.text


def test_upload_renders_tiles_queue_and_issue_codes():
    page=upload().text

    assert "Data quality score" in page
    assert "Review queue (2)" in page
    assert re.search(r'value="E2=E1"\s+checked',page) #confident fix pre-selected
    assert "E404 is not in the file" in page
    assert "MANAGER_NOT_FOUND" in page


def test_projection_callout():
    page=upload().text

    assert "Accepting the <strong>1</strong> pre-selected fixes reconnects" in page


def test_apply_round_trip_fixes_only_selected_rows():
    page=upload().text
    csv_text=html.unescape(re.search(r'<textarea name="csv_text" hidden>(.*?)</textarea>',page,re.S).group(1))

    response=client.post("/apply",data={"csv_text":csv_text,"fix":["E2=E1"]})

    assert response.status_code==200
    assert response.headers["content-disposition"]=='attachment; filename="corrected.csv"'
    corrected=response.text
    assert "E2,Bob,bob@co.com,E1,alice@co.com,Eng" in corrected
    assert "E3,Cara,cara@co.com,E404,,Eng" in corrected #untouched
    issues=run_import_preview(corrected.encode()).issues
    assert [i.employee_id for i in issues]==["E3"]


def test_apply_ignores_fixes_for_unknown_employees():
    response=client.post("/apply",data={"csv_text":CSV,"fix":["NOPE=E1","E3=GHOST"]})

    assert response.text.replace("\r\n","\n")==CSV


def test_api_preview_returns_json():
    response=client.post("/api/preview",files={"file":("org.csv",CSV,"text/csv")})
    body=response.json()

    assert body["summary"]=={"total_rows":3,"accepted":3,"rejected":0,"errors":0,"warnings":2}
    assert [i["tier"] for i in body["review_queue"]]==["auto","manual"]
    assert body["review_queue"][0]["suggestion"]["reason"]=="id_format"
    assert body["projection"]["connected_after"]==2


def test_oversized_upload_is_rejected():
    response=client.post("/upload",files={"file":("big.csv",b"x"*(MAX_UPLOAD_BYTES+10),"text/csv")})

    assert response.status_code==200
    assert "This file could not be read" in response.text
    assert "larger than the 5 MB limit" in response.text


def test_events_are_logged(caplog):
    with caplog.at_level("INFO",logger="hris_import.events"):
        upload()

    assert '"event": "import_previewed"' in caplog.text
    assert '"queue_auto": 1' in caplog.text


def test_apply_rejects_unreadable_file():
    response=client.post("/apply",data={"csv_text":"not,a,valid,header\n","fix":["E2=E1"]})

    assert response.status_code==400


def test_csv_content_cannot_break_out_of_the_page():
    page=upload(CSV+'E9,"</textarea><script>alert(1)</script>",e9@co.com,,,Eng\n').text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;/textarea&gt;&lt;script&gt;" in page


def test_landing_page_offers_samples_and_privacy_notice():
    page=client.get("/").text

    assert 'href="/try/messy-org"' in page and 'href="/try/original"' in page
    assert "please don't upload real employee data" in page


def test_try_sample_renders_results_without_an_upload():
    page=client.get("/try/messy-org").text

    assert "Results for <strong>synthetic_org_500.csv</strong>" in page
    assert re.search(r"Review queue \(\d+\)",page)
    assert '<textarea name="csv_text" hidden>employee_id,' in page #fixes still work on samples


def test_unknown_sample_is_404():
    assert client.get("/try/../../etc/passwd").status_code==404
    assert client.get("/try/nope").status_code==404


def test_events_tag_where_the_data_came_from(caplog):
    with caplog.at_level("INFO",logger="hris_import.events"):
        client.get("/try/original")

    assert '"source": "sample:original"' in caplog.text
