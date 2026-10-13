from fastapi import FastAPI, UploadFile, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pipeline import run_import_preview, MAX_UPLOAD_BYTES

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "result.html", {"result": None})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile):
    # read one byte past the limit so oversized files are rejected without loading them whole
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    result = run_import_preview(content)
    return templates.TemplateResponse(request, "result.html", {"result": result})
