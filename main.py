"""Plant Précis Producer — FastAPI entry point."""

import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.database import init_db, get_connection
from core.synonym_resolver import SynonymResolver
from core.query import QueryEngine
from core.compile_json import export_json
from core.ingestion import probe_pdf, register_source, build_index

CONFIG_PATH = "config.json"
DATA_DIR = "."


def load_config() -> dict:
    defaults = {
        "port": 7734,
        "data_dir": ".",
        "zotero_enabled": False,
        "zotero_library_path": None,
        "default_output_formats": ["pdf"],
        "dark_mode": True,
    }
    if Path(CONFIG_PATH).exists():
        with open(CONFIG_PATH) as f:
            user_config = json.load(f)
        defaults.update(user_config)
    return defaults


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(DATA_DIR)
    yield


app = FastAPI(
    title="Plant Précis Producer",
    description="Local-first botanical research tool",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- Page routes ---

@app.get("/", response_class=HTMLResponse)
async def page_query(request: Request):
    return templates.TemplateResponse("query.html", {"request": request})


@app.get("/ingestion", response_class=HTMLResponse)
async def page_ingestion(request: Request):
    return templates.TemplateResponse("ingestion.html", {"request": request})


@app.get("/library", response_class=HTMLResponse)
async def page_library(request: Request):
    return templates.TemplateResponse("library.html", {"request": request})


# --- API routes ---

@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    engine = QueryEngine(DATA_DIR)
    results = engine.search(
        input_string=body.get("input_string", ""),
        lens_filters=body.get("lens_filters"),
    )
    return JSONResponse(results)


@app.post("/api/query/export")
async def api_export(request: Request):
    body = await request.json()
    engine = QueryEngine(DATA_DIR)
    results = engine.search(
        input_string=body.get("input_string", ""),
        lens_filters=body.get("lens_filters"),
    )
    output_path = export_json(results)
    return JSONResponse({"path": output_path, "results": results})


@app.get("/api/sources")
async def api_sources():
    conn = get_connection(DATA_DIR)
    try:
        rows = conn.execute("SELECT * FROM sources ORDER BY title").fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        conn.close()


@app.get("/api/sources/{source_id}")
async def api_source(source_id: str):
    conn = get_connection(DATA_DIR)
    try:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Source not found")
        return JSONResponse(dict(row))
    finally:
        conn.close()


@app.delete("/api/sources/{source_id}")
async def api_delete_source(source_id: str):
    conn = get_connection(DATA_DIR)
    try:
        row = conn.execute("SELECT index_file FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Source not found")
        # Remove index file if it exists
        if row["index_file"] and Path(row["index_file"]).exists():
            Path(row["index_file"]).unlink()
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        conn.commit()
        return JSONResponse({"deleted": source_id})
    finally:
        conn.close()


@app.post("/api/ingest/probe")
async def api_probe(file: UploadFile = File(...)):
    # Save uploaded file temporarily for probing
    tmp_path = Path("_uploads") / file.filename
    tmp_path.parent.mkdir(exist_ok=True)
    with open(tmp_path, "wb") as f:
        content = await file.read()
        f.write(content)
    try:
        result = probe_pdf(str(tmp_path))
        return JSONResponse(result)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/ingest/register")
async def api_register(request: Request):
    body = await request.json()
    source_id = register_source(body, DATA_DIR)
    return JSONResponse({"id": source_id})


@app.post("/api/ingest/build-index/{source_id}")
async def api_build_index(source_id: str):
    try:
        index_path = build_index(source_id, DATA_DIR)
        return JSONResponse({"source_id": source_id, "index_file": index_path})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/synonyms/{canonical}")
async def api_synonyms(canonical: str):
    resolver = SynonymResolver(DATA_DIR)
    names = resolver.get_all_names(canonical)
    return JSONResponse({"canonical": canonical, "synonyms": names})


@app.post("/api/synonyms")
async def api_add_synonym(request: Request):
    body = await request.json()
    resolver = SynonymResolver(DATA_DIR)
    resolver.add_synonym(
        canonical_binomial=body["canonical_binomial"],
        name_string=body["name_string"],
        name_type=body.get("name_type", "common"),
        language=body.get("language", "en"),
        source=body.get("source", "user_added"),
    )
    return JSONResponse({"added": body["name_string"]})


@app.get("/api/resolve/{query}")
async def api_resolve(query: str):
    resolver = SynonymResolver(DATA_DIR)
    result = resolver.resolve(query)
    if not result:
        return JSONResponse({"match": None}, status_code=200)
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn

    config = load_config()
    uvicorn.run("main:app", host="0.0.0.0", port=config["port"], reload=True)
