import sys
import os
sys.path.insert(0,os.path.join(os.path.dirname(__file__),".."))

from pipeline import run_import_preview, MAX_UPLOAD_BYTES

HEADER="employee_id,employee_name,email,manager_id,manager_email,department\n"

def make_csv(rows:str,header:str=HEADER)->bytes:
    return (header+rows).encode('utf-8')

def messages(result)->list[str]:
    return [e.message for e in result.errors]


def test_manager_email_matches_regardless_of_case():

    #regression: emails were once compared without lowercasing,
    #so an uppercase manager_email silently failed to resolve.

    csv_bytes=make_csv(
        "E1,Alice,Alice@Co.com,,,Eng\n"
        "E2,Bob,bob@co.com,,ALICE@CO.COM,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert result.errors==[]
    assert result.manager_report_counts=={"E1":1}


def test_missing_email_is_rejected():
    result=run_import_preview(make_csv("E1,Alice,,,,Eng\n"))

    assert result.accepted_employees==[]
    assert messages(result)==["Missing required email."]


def test_missing_employee_id_is_rejected():
    result=run_import_preview(make_csv(",Alice,alice@co.com,,,Eng\n"))

    assert result.accepted_employees==[]
    assert messages(result)==["Missing required employee_id."]


def test_header_whitespace_and_case_are_normalised():
    header=" Employee_ID ,employee_name, EMAIL ,manager_id,manager_email,department\n"
    result=run_import_preview(make_csv("E1,Alice,alice@co.com,,,Eng\n",header))

    assert result.errors==[]
    assert [e.employee_id for e in result.accepted_employees]==["E1"]


def test_missing_columns_reported_as_file_error():
    result=run_import_preview(b"employee_id,email\nE1,a@co.com\n")

    assert result.total_rows==0
    assert messages(result)==["Missing required columns: department, employee_name, manager_email, manager_id"]


def test_utf8_bom_is_stripped():
    result=run_import_preview(b"\xef\xbb\xbf"+make_csv("E1,Alice,alice@co.com,,,Eng\n"))

    assert result.errors==[]
    assert len(result.accepted_employees)==1


def test_non_utf8_file_reported_as_file_error():
    latin1_bytes=make_csv("E1,Renée,r@co.com,,,Eng\n").decode("utf-8").encode("latin-1")
    result=run_import_preview(latin1_bytes)

    assert messages(result)==["File is not valid UTF-8 text."]


def test_row_numbers_follow_source_lines_with_multiline_fields():

    #E1's quoted name spans two lines, so E2 starts on line 4, not 3.

    csv_bytes=make_csv(
        'E1,"Alice\nSmith",alice@co.com,,,Eng\n'
        "E2,Bob,bob@co.com,MISSING,,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert [(e.row_number,e.employee_id) for e in result.errors]==[(4,"E2")]


def test_blank_lines_are_skipped_without_shifting_row_numbers():
    csv_bytes=make_csv(
        "E1,Alice,alice@co.com,,,Eng\n"
        "\n"
        ",,,,,\n"
        "E2,Bob,bob@co.com,MISSING,,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert result.total_rows==2
    assert [e.row_number for e in result.errors]==[5]


def test_self_management_is_an_error():
    result=run_import_preview(make_csv("E1,Alice,alice@co.com,E1,,Eng\n"))

    assert messages(result)==["Employee cannot manage themselves."]
    assert result.roots==[]


def test_unresolved_manager_is_not_a_root():
    result=run_import_preview(make_csv("E1,Alice,alice@co.com,E404,,Eng\n"))

    assert messages(result)==["Manager reference could not be found."]
    assert result.roots==[]
    assert len(result.accepted_employees)==1


def test_oversized_upload_is_rejected_before_parsing():
    result=run_import_preview(b"x"*(MAX_UPLOAD_BYTES+1))

    assert result.total_rows==0
    assert "larger than" in messages(result)[0]


def test_output_order_is_deterministic():
    csv_bytes=make_csv(
        "Z1,Zed,z@co.com,,,Eng\n"
        "A1,Ann,a@co.com,,,Eng\n"
        "B1,Ben,b@co.com,A1,,Eng\n"
        "B2,Bea,b2@co.com,Z1,,Eng\n"
        "B3,Bo,b3@co.com,Z1,,Eng\n"
        "X1,Xi,x1@co.com,NOPE,,Eng\n"
        ",NoId,noid@co.com,,,Eng\n"
    )
    result=run_import_preview(csv_bytes)

    assert [r.employee_id for r in result.roots]==["A1","Z1"]
    assert list(result.manager_report_counts)==["Z1","A1"] #most reports first
    assert [e.row_number for e in result.errors]==[7,8] #sorted by row, not by pass
