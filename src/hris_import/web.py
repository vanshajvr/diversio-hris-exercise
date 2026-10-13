import json
import logging
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from .metrics import compute_metrics
from .pipeline import MAX_UPLOAD_BYTES, run_import_preview
from .review import apply_fixes, review
from .suggestions import DEFAULT_THRESHOLD

app = FastAPI(title="HRIS Import Preview")
# resolved from this file, so the app works no matter which directory uvicorn starts in
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# one JSON line per product event; docs/PRD.md defines what each field is for.
# uvicorn only configures its own loggers, so without this handler the events would be dropped.
events = logging.getLogger("hris_import.events")
events.setLevel(logging.INFO)
if not events.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    events.addHandler(_handler)


def _event(name: str, **fields) -> None:
    events.info(json.dumps({"event": name, **fields}))


def _preview(content: bytes) -> dict:
    result, queue = review(content)
    metrics = compute_metrics(result) if result.total_rows else None
    tiers = Counter(item.tier for item in queue.items)
    _event(
        "import_previewed",
        rows=result.total_rows,
        issues=len(result.issues),
        queue_auto=tiers["auto"],
        queue_review=tiers["review"],
        queue_manual=tiers["manual"],
        quality_score=metrics.quality.score if metrics else None,
        projected_score=queue.projection.score_after if queue.projection else None,
    )
    return {"result": result, "metrics": metrics, "queue": queue}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "result.html", {"result": None})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile):
    # read one byte past the limit so oversized files are rejected without loading them whole
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    context = _preview(content)
    # no server-side storage: the file travels back with the fix form, so applying fixes stays stateless
    context["csv_text"] = content.decode("utf-8-sig") if context["result"].total_rows else ""
    context["threshold"] = DEFAULT_THRESHOLD
    return templates.TemplateResponse(request, "result.html", context)


@app.post("/apply")
def apply(csv_text: Annotated[str, Form()], fix: Annotated[list[str] | None, Form()] = None):
    content = csv_text.encode("utf-8")
    if len(content) > MAX_UPLOAD_BYTES:
        return Response("File is larger than the upload limit.", status_code=413)
    result = run_import_preview(content)
    if result.total_rows == 0:
        return Response("The submitted file could not be read; upload it again.", status_code=400)
    # each checkbox is "employee_id=manager_id"; apply_fixes ignores ids that aren't accepted employees
    fixes = dict(f.split("=", 1) for f in fix or [] if "=" in f)
    _event("fixes_applied", fixes=len(fixes), rows=result.total_rows)
    return Response(
        apply_fixes(content, result, fixes),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="corrected.csv"'},
    )


@app.post("/api/preview")
async def api_preview(file: UploadFile) -> dict:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    context = _preview(content)
    result, metrics, queue = context["result"], context["metrics"], context["queue"]
    return {
        "summary": {
            "total_rows": result.total_rows,
            "accepted": len(result.accepted_employees),
            "rejected": result.rejected_rows,
            "errors": len(result.errors),
            "warnings": len(result.warnings),
        },
        "metrics": asdict(metrics) if metrics else None,
        "issues": [asdict(i) for i in result.issues],
        "review_queue": [asdict(i) for i in queue.items],
        "projection": asdict(queue.projection) if queue.projection else None,
    }
