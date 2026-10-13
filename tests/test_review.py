from hris_import.pipeline import run_import_preview
from hris_import.review import AUTO, MANUAL, REVIEW, apply_fixes, auto_fixes, build_review_queue, review

HEADER="employee_id,employee_name,email,manager_id,manager_email,department\n"

#VP has a team of 3; the VP's own manager reference is broken, so all 4 are cut off.
#IC has a broken reference too, but only cuts off themselves.
ORG=(
    "CEO,Ceo,ceo@co.com,,,Exec\n"
    "VP,Vp,vp@co.com,ceo,,Eng\n" #format drift -> confident fix
    "T1,Team One,t1@co.com,VP,,Eng\n"
    "T2,Team Two,t2@co.com,VP,,Eng\n"
    "T3,Team Three,t3@co.com,VP,,Eng\n"
    "IC,Lone,ic@co.com,GHOST,,Sales\n"
    "A,Gone One,a@co.com,LEFT,,Ops\n"
    "B,Gone Two,b@co.com,LEFT,,Ops\n"
    "X,Loop X,x@co.com,Y,,Ops\n"
    "Y,Loop Y,y@co.com,X,,Ops\n"
    "Z,Under Loop,z@co.com,X,,Ops\n"
)

def queue(csv:str=ORG):
    return build_review_queue(run_import_preview((HEADER+csv).encode()))


def test_queue_is_ordered_by_people_affected():
    items=queue()

    assert [(i.key,i.people_affected,i.tier) for i in items]==[
        ("VP",4,AUTO),
        ("cycle:X",3,MANUAL), #X and Y, plus Z hanging below the loop
        ("missing:LEFT",2,MANUAL),
        ("IC",1,MANUAL),
    ]


def test_rows_pointing_at_the_same_absent_manager_are_one_item():
    (item,)=[i for i in queue() if i.key=="missing:LEFT"]

    assert item.employee_ids==["A","B"]
    assert item.title=="Manager LEFT is not in the file but 2 people report to them"


def test_cycle_item_names_the_loop():
    (item,)=[i for i in queue() if i.key=="cycle:X"]

    assert item.title=="Reporting loop: Loop X → Loop Y → Loop X"


def test_low_confidence_suggestion_goes_to_review():
    #T9 is one edit from VP but in another department: a candidate, not a confident fix
    items=queue(ORG+"N,New,n@co.com,VP9,,Sales\n")
    (item,)=[i for i in items if i.key=="N"]

    assert item.tier==REVIEW
    assert item.suggestion.suggested_manager_id=="VP"


def test_apply_fixes_changes_only_manager_cells_of_fixed_rows():
    source=(HEADER+ORG).encode()
    result=run_import_preview(source)
    fixed=apply_fixes(source,result,{"VP":"CEO"}).decode()

    before=(HEADER+ORG).splitlines()
    after=fixed.splitlines()
    changed=[(b,a) for b,a in zip(before,after,strict=True) if b!=a]
    assert changed==[("VP,Vp,vp@co.com,ceo,,Eng","VP,Vp,vp@co.com,CEO,ceo@co.com,Eng")]


def test_apply_fixes_preserves_extra_columns_and_padding():
    source=(b"employee_id,employee_name,email,manager_id,manager_email,department,location\n"
            b"CEO,Ceo,ceo@co.com,,,Exec,NYC\n"
            b" E1 ,Ed,ed@co.com,ceo,,Eng,\"Paris, FR\"\n")
    result=run_import_preview(source)
    fixed=apply_fixes(source,result,{"E1":"CEO"}).decode()

    assert fixed.splitlines()[2]==' E1 ,Ed,ed@co.com,CEO,ceo@co.com,Eng,"Paris, FR"'


def test_review_projects_the_effect_of_auto_fixes():
    result,q=review((HEADER+ORG).encode())

    assert auto_fixes(q.items)=={"VP":"CEO"}
    assert q.projection.fixes==1
    assert q.projection.connected_after-q.projection.connected_before==4
    assert q.projection.score_after>q.projection.score_before


def test_review_of_unreadable_file_is_empty():
    result,q=review(b"\xff\xfe")

    assert q.items==[] and q.projection is None
