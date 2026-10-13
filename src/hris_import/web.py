from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .pipeline import MAX_UPLOAD_BYTES, run_import_preview

app = FastAPI(title="HRIS Import Preview")
# resolved from this file, so the app works no matter which directory uvicorn starts in
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "result.html", {"result": None})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile):
    # read one byte past the limit so oversized files are rejected without loading them whole
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    result = run_import_preview(content)
    return templates.TemplateResponse(request, "result.html", {"result": result})
