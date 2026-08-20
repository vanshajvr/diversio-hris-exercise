from fastapi import FastAPI, UploadFile, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pipeline import run_import_preview

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "result.html", {"result": None})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile):
    content = await file.read()
    result = run_import_preview(content)
    return templates.TemplateResponse(request, "result.html", {"result": result})