import json

import pytest

from hris_import.__main__ import main
from hris_import.evaluation import evaluate_detection, format_benchmark, run_benchmark, wilson_interval
from hris_import.metrics import compute_metrics
from hris_import.models import IssueCode
from hris_import.pipeline import run_import_preview
from hris_import.synthetic import COSMETIC, CYCLE_EDGE, ID_TYPO, KINDS, MISSING_DEPARTMENT, generate_org, typo


def test_clean_org_has_no_issues_and_a_realistic_shape():
    org=generate_org(500,seed=3,corruption_rate=0)
    m=compute_metrics(run_import_preview(org.csv_bytes))

    assert org.corruptions==[]
    assert m.issue_counts=={}
    assert m.quality.score==100.0
    assert m.roots==1
    assert 5<=m.layers<=8 #500 people: wide, not a chain
    assert 3<=m.span.median<=8
    assert m.span.narrow_span_manager_ids==[] #no single-report managers by construction


def test_generation_is_deterministic_per_seed():
    assert generate_org(300,seed=9).csv_bytes==generate_org(300,seed=9).csv_bytes
    assert generate_org(300,seed=9).csv_bytes!=generate_org(300,seed=10).csv_bytes


def test_every_kind_is_injected():
    org=generate_org(500,seed=1,corruption_rate=0.01)

    assert {c.kind for c in org.corruptions}==set(KINDS)


@pytest.mark.parametrize("seed",range(10))
@pytest.mark.parametrize("density",[1.0,0.1])
def test_validator_catches_every_detectable_corruption(seed,density):
    org=generate_org(400,seed=seed,corruption_rate=0.01,id_density=density)
    report=evaluate_detection(org,run_import_preview(org.csv_bytes))

    for o in report.outcomes:
        c=o.corruption
        if c.expected_issue is not None:
            assert o.expected_code_raised,f"{c.kind} on {c.employee_id} not flagged as {c.expected_issue}"
        if c.kind in (COSMETIC,MISSING_DEPARTMENT):
            assert not o.detected,f"{c.kind} on {c.employee_id} should not raise an issue"
    assert report.unexplained_issues==[]


def test_cycle_corruption_flags_the_whole_loop():
    org=generate_org(400,seed=2,corruption_rate=0.01)
    result=run_import_preview(org.csv_bytes)

    for c in org.corruptions:
        if c.kind==CYCLE_EDGE:
            assert set(c.affected_ids)<=result.cyclic_employee_ids


def test_id_typo_that_hits_a_real_id_is_only_caught_with_email():

    #with sequential ids many typos land on someone real. id-only rows then go silent,
    #rows that also carry manager_email are always caught as a conflict.

    silent_id_only=0
    for seed in range(15):
        org=generate_org(500,seed=seed,corruption_rate=0.02,id_density=1.0)
        report=evaluate_detection(org,run_import_preview(org.csv_bytes))
        for o in report.outcomes:
            c=o.corruption
            if c.kind==ID_TYPO and c.collides and c.ref_style=="both":
                assert o.expected_code_raised and c.expected_issue==IssueCode.MANAGER_CONFLICT
            if c.kind==ID_TYPO and c.collides and c.ref_style=="id" and not o.detected:
                silent_id_only+=1
    assert silent_id_only>0 #the blind spot is real, not hypothetical


def test_typo_is_always_one_edit_away():
    import random
    rng=random.Random(0)
    for _ in range(200):
        out=typo("1234",rng,"0123456789")
        assert out!="1234"
        assert abs(len(out)-4)<=1


def test_wilson_interval():
    lo,hi=wilson_interval(0,50)
    assert lo==0.0 and 0.05<hi<0.08
    lo,hi=wilson_interval(10,100)
    assert lo<0.10<hi
    assert wilson_interval(0,0)==(0.0,1.0)


def test_benchmark_summary_and_format():
    b=run_benchmark(200,seeds=3,densities=(1.0,))

    assert b.runs==3
    assert b.unexplained_issues==0
    text=format_benchmark(b)
    assert "| `email_mismatch` |" in text
    assert "manager_id only" in text


def test_cli_generate_writes_csv_and_truth(tmp_path,capsys):
    out=tmp_path/"org.csv"
    assert main(["generate",str(out),"--size","120","--seed","4"])==0

    truth=json.loads((tmp_path/"org_truth.json").read_text())
    assert out.read_text().startswith("employee_id,employee_name,email,manager_id,manager_email,department")
    assert {t["kind"] for t in truth}==set(KINDS)
    assert "labelled corruptions" in capsys.readouterr().out
