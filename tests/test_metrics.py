import json
from pathlib import Path

import pytest

from hris_import.__main__ import main
from hris_import.metrics import compute_metrics
from hris_import.pipeline import run_import_preview
from hris_import.synthetic import generate_org

HEADER="employee_id,employee_name,email,manager_id,manager_email,department\n"
SAMPLE=Path(__file__).resolve().parents[1]/"data"/"sample_hris.csv"

def make_csv(rows:str)->bytes:
    return (HEADER+rows).encode('utf-8')

def metrics_for(csv_bytes:bytes):
    return compute_metrics(run_import_preview(csv_bytes))

#CEO -> VP1 -> (M1 -> 3 ICs), VP2 -> 1 IC; X reports to a missing manager; C1 <-> C2 is a cycle.
SMALL_ORG=make_csv(
    "CEO,Ceo,ceo@co.com,,,Exec\n"
    "VP1,Vp One,vp1@co.com,CEO,,Eng\n"
    "VP2,Vp Two,vp2@co.com,CEO,,Sales\n"
    "M1,Manager,m1@co.com,VP1,,Eng\n"
    "I1,Ic One,i1@co.com,M1,,Eng\n"
    "I2,Ic Two,i2@co.com,M1,,Eng\n"
    "I3,Ic Three,i3@co.com,M1,,\n"
    "I4,Ic Four,i4@co.com,VP2,,Sales\n"
    "X,Lost,x@co.com,GHOST,,Sales\n"
    "C1,Loop One,c1@co.com,C2,,Ops\n"
    "C2,Loop Two,c2@co.com,C1,,Ops\n"
    ",No Id,noid@co.com,,,Ops\n"
)


def test_hierarchy_shape():
    m=metrics_for(SMALL_ORG)

    assert m.headcount==11
    assert m.layers==4
    assert m.depth_distribution=={0:1,1:2,2:2,3:3}
    assert m.disconnected_employee_ids==["C1","C2","X"]
    assert m.largest_orgs[:3]==[("CEO","Ceo",7),("VP1","Vp One",4),("M1","Manager",3)]


def test_span_of_control():
    span=metrics_for(SMALL_ORG).span

    #CEO 2, VP1 1, VP2 1, M1 3, C1 1, C2 1
    assert span.managers==6
    assert span.max==3
    assert span.distribution=={"1":4,"2-4":2,"5-8":0,"9-12":0,"13+":0}
    assert span.narrow_span_manager_ids==["C1","C2","VP1","VP2"]


def test_department_breakdown_counts_blank_department():
    depts={d.department:d for d in metrics_for(SMALL_ORG).departments}

    assert depts["Eng"].headcount==4
    assert depts["Eng"].managers==2
    assert depts["Eng"].ics_per_manager==1.0
    assert depts["(blank)"].headcount==1
    assert depts["Exec"].ics_per_manager==0.0


def test_data_quality_and_funnel():
    m=metrics_for(SMALL_ORG)

    assert m.quality.validity_rate==11/12
    assert m.quality.resolution_rate==9/10 #X is the only manager ref that fails
    assert m.quality.connectivity_rate==8/11
    assert m.quality.completeness_rate==10/11
    assert m.quality.score==round(100*(11/12+9/10+8/11+10/11)/4,1)
    assert [s.count for s in m.funnel]==[12,11,10,8]
    assert m.issue_counts=={"REPORTING_CYCLE":2,"MANAGER_NOT_FOUND":1,"MISSING_EMPLOYEE_ID":1}


def test_unparseable_file_scores_zero():
    m=metrics_for(b"not,a,valid,header\n")

    assert m.quality.score==0.0
    assert m.headcount==0
    assert m.layers==0


@pytest.mark.parametrize("csv_bytes",[SAMPLE.read_bytes(),SMALL_ORG,generate_org(2000,seed=7).csv_bytes],
                         ids=["sample","small","random-2000"])
def test_metrics_are_internally_consistent(csv_bytes):

    #independent views of the same org must agree with each other

    result=run_import_preview(csv_bytes)
    m=compute_metrics(result)
    connected=m.funnel[-1].count

    assert sum(m.depth_distribution.values())==connected
    assert connected+len(m.disconnected_employee_ids)==m.headcount
    assert m.managers+m.individual_contributors==m.headcount
    assert sum(d.headcount for d in m.departments)==m.headcount
    assert sum(d.managers for d in m.departments)==m.managers
    assert sum(m.span.distribution.values())==m.span.managers
    assert sum(m.issue_counts.values())==len(result.issues)
    assert [s.count for s in m.funnel]==sorted((s.count for s in m.funnel),reverse=True) #funnel never grows
    #with a single root, that root's org is the whole connected tree
    if m.roots==1:
        assert m.largest_orgs[0][0]==result.roots[0].employee_id
        assert m.largest_orgs[0][2]==connected-1


def test_cli_text_and_json(capsys):
    assert main(["report",str(SAMPLE)])==0
    assert "Data quality score: 92.9/100" in capsys.readouterr().out

    assert main(["report",str(SAMPLE),"--json"])==0
    assert json.loads(capsys.readouterr().out)["layers"]==4


def test_cli_fails_cleanly_on_bad_file(capsys,tmp_path):
    bad=tmp_path/"bad.csv"
    bad.write_bytes(b"\xff\xfe")

    assert main(["report",str(bad)])==1
    assert "not valid UTF-8" in capsys.readouterr().err

