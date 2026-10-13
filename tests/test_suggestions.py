import json

import pytest

from hris_import.__main__ import main
from hris_import.evaluation import (
    CALIBRATION_SEED_START,
    DEFAULT_THRESHOLD,
    calibrate_confidence,
    collect_suggestion_outcomes,
    format_suggestion_benchmark,
    precision_coverage,
)
from hris_import.pipeline import run_import_preview
from hris_import.suggestions import (
    AMBIGUOUS,
    CONFIDENCE,
    CONFLICT_EMAIL_WRONG,
    CONFLICT_ID_TYPO,
    EMAIL_DOMAIN,
    EMAIL_RESOLVES,
    ID_FORMAT,
    ID_TYPO,
    MISSING_MANAGER,
    NO_CANDIDATE,
    TYPO_OTHER_DEPT,
    TYPO_TIEBREAK,
    SuggestOptions,
    edits1,
    suggest_fixes,
)

HEADER="employee_id,employee_name,email,manager_id,manager_email,department\n"

#a small org every test adds one broken row to
ORG=(
    "EMP-100,Ceo,ceo@co.com,,,Exec\n"
    "EMP-200,Eng Lead,eng.lead@co.com,EMP-100,,Eng\n"
    "EMP-300,Sales Lead,sales.lead@co.com,EMP-100,,Sales\n"
    "EMP-201,Dev,dev@co.com,EMP-200,,Eng\n"
)

def suggestion_for(row:str,employee_id:str="EMP-999",options:SuggestOptions|None=None):
    result=run_import_preview((HEADER+ORG+row+"\n").encode())
    (s,)=[s for s in suggest_fixes(result,options) if s.employee_id==employee_id]
    return s


@pytest.mark.parametrize("bad_id",["emp-200","EMP200","EMP 200","200"])
def test_id_format_drift(bad_id):
    s=suggestion_for(f"EMP-999,New,new@co.com,{bad_id},,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",ID_FORMAT)


def test_email_resolves_when_id_is_broken():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-2O0,eng.lead@co.com,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",EMAIL_RESOLVES)


def test_legacy_email_domain():
    s=suggestion_for("EMP-999,New,new@co.com,,eng.lead@old-co.com,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",EMAIL_DOMAIN)


def test_single_id_typo_in_same_department():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-2000,,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",ID_TYPO)
    assert s.confidence>=DEFAULT_THRESHOLD


def test_single_typo_in_other_department_is_low_confidence():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-3000,,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-300",TYPO_OTHER_DEPT)
    assert s.confidence<DEFAULT_THRESHOLD


def test_tiebreak_prefers_same_department_manager():
    #EMP-20 is one edit from both EMP-200 and EMP-201, both in Eng; only EMP-200 already manages people
    s=suggestion_for("EMP-999,New,new@co.com,EMP-20,,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",TYPO_TIEBREAK)
    assert s.confidence<DEFAULT_THRESHOLD


def test_tiebreak_can_be_switched_off():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-20,,Eng",options=SuggestOptions(tiebreak=False))

    assert (s.suggested_manager_id,s.reason)==(None,AMBIGUOUS)


def test_shared_missing_reference_is_not_guessed():
    #two rows point at EMP-2000, one edit from EMP-200: a missing person, not a repeated typo
    rows="EMP-998,A,a@co.com,EMP-2000,,Eng\nEMP-999,B,b@co.com,EMP-2000,,Eng"
    s=suggestion_for(rows)

    assert (s.suggested_manager_id,s.reason)==(None,MISSING_MANAGER)
    assert "referenced by 2 rows" in s.explanation


def test_never_suggests_a_fix_that_creates_a_cycle():
    #EMP-2010 is one edit from EMP-200 (self) and EMP-201 (EMP-200's own report): both must be excluded
    result=run_import_preview((HEADER+ORG.replace("EMP-200,Eng Lead,eng.lead@co.com,EMP-100","EMP-200,Eng Lead,eng.lead@co.com,EMP-2010")).encode())
    (s,)=suggest_fixes(result)

    assert s.employee_id=="EMP-200"
    assert (s.suggested_manager_id,s.reason)==(None,NO_CANDIDATE)


def test_conflict_where_email_is_wrong():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-200,sales.lead@co.com,Eng")

    assert (s.suggested_manager_id,s.reason)==("EMP-200",CONFLICT_EMAIL_WRONG)


def test_conflict_where_id_is_the_typo():
    #manager_id EMP-202 (Ops) is one edit from EMP-200 (Eng), who owns manager_email: the id is the typo
    rows="EMP-202,Ops,ops@co.com,EMP-100,,Ops\nEMP-999,New,new@co.com,EMP-202,eng.lead@co.com,Eng"
    s=suggestion_for(rows)

    assert (s.suggested_manager_id,s.reason)==("EMP-200",CONFLICT_ID_TYPO)


def test_conflict_with_no_department_evidence_abstains():
    s=suggestion_for("EMP-999,New,new@co.com,EMP-201,eng.lead@co.com,Eng")

    assert (s.suggested_manager_id,s.reason)==(None,AMBIGUOUS)


def test_edits1():
    variants=edits1("ab","abc")

    assert "ba" in variants and "a" in variants and "abc" in variants and "cb" in variants
    assert "ab" not in variants


def test_sample_file_gets_no_risky_suggestions():
    from pathlib import Path
    sample=Path(__file__).resolve().parents[1]/"data"/"sample_hris.csv"
    suggestions=suggest_fixes(run_import_preview(sample.read_bytes()))

    assert {s.employee_id:s.suggested_manager_id for s in suggestions}=={"DIV-1600":None,"DIV-1601":None}


def test_held_out_precision_at_operating_threshold():
    outcomes=collect_suggestion_outcomes(500,seeds=15)
    pc=precision_coverage(outcomes,DEFAULT_THRESHOLD)

    assert pc.precision>=0.98
    assert pc.coverage>=0.85


def test_calibration_seeds_are_disjoint_from_reported_seeds():
    assert CALIBRATION_SEED_START>1000


def test_stated_confidence_matches_recalibration():
    #if the engine changes, CONFIDENCE has to be re-measured; this catches it going stale
    measured=calibrate_confidence(seeds=25)
    for reason,observed in measured.items():
        assert abs(CONFIDENCE[reason]-min(observed,0.99))<=0.1,f"{reason}: stated {CONFIDENCE[reason]}, measured {observed}"


def test_benchmark_report_renders():
    outcomes=collect_suggestion_outcomes(200,seeds=2,densities=(1.0,))
    text=format_suggestion_benchmark(outcomes,{"no tie-break":outcomes})

    assert "Calibration" in text and "Ablations" in text


def test_cli_suggest(capsys,tmp_path):
    org=tmp_path/"org.csv"
    org.write_text(HEADER+ORG+"EMP-999,New,new@co.com,EMP200,,Eng\n")

    assert main(["suggest",str(org)])==0
    assert "-> EMP-200" in capsys.readouterr().out
    assert main(["suggest",str(org),"--json"])==0
    assert json.loads(capsys.readouterr().out)[0]["reason"]==ID_FORMAT
