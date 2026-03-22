"""Plant Précis Producer — FastAPI entry point."""

import asyncio
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
from core.compile_pdf import compile_precis, CompilationError
from core.ingestion import probe_source, register_source, build_index

CONFIG_PATH = "config.json"
DATA_DIR = "."
UPLOADS_DIR = Path("_uploads")


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
    UPLOADS_DIR.mkdir(exist_ok=True)
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


# --- Query API routes ---

@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    engine = QueryEngine(DATA_DIR)
    results = engine.search(
        input_string=body.get("input_string", ""),
        lens_filters=body.get("lens_filters"),
    )

    output_formats = body.get("output_formats", [])
    response = {"results": results}

    if "json" in output_formats:
        json_path = export_json(results)
        response["json_path"] = json_path

    if "pdf" in output_formats:
        try:
            pdf_path = await asyncio.to_thread(compile_precis, results, DATA_DIR)
            response["pdf_path"] = pdf_path
        except CompilationError as e:
            response["pdf_error"] = str(e)

    return JSONResponse(response)


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


@app.post("/api/query/compile-pdf")
async def api_compile_pdf(request: Request):
    body = await request.json()
    engine = QueryEngine(DATA_DIR)
    results = engine.search(
        input_string=body.get("input_string", ""),
        lens_filters=body.get("lens_filters"),
    )
    try:
        pdf_path = await asyncio.to_thread(compile_precis, results, DATA_DIR)
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=Path(pdf_path).name,
        )
    except CompilationError as e:
        raise HTTPException(status_code=422, detail=str(e))


# --- Source API routes ---

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
        if row["index_file"] and Path(row["index_file"]).exists():
            Path(row["index_file"]).unlink()
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        conn.commit()
        return JSONResponse({"deleted": source_id})
    finally:
        conn.close()


@app.patch("/api/sources/{source_id}/verify")
async def api_verify_source(source_id: str):
    conn = get_connection(DATA_DIR)
    try:
        row = conn.execute("SELECT id, index_status FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Source not found")
        if row["index_status"] != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Source index is '{row['index_status']}', must be 'ready' to verify",
            )
        conn.execute(
            "UPDATE sources SET verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (source_id,),
        )
        conn.commit()
        return JSONResponse({"verified": source_id})
    finally:
        conn.close()


# --- Ingestion API routes ---

@app.post("/api/ingest/probe")
async def api_probe(file: UploadFile = File(...)):
    upload_path = UPLOADS_DIR / file.filename
    UPLOADS_DIR.mkdir(exist_ok=True)
    with open(upload_path, "wb") as f:
        content = await file.read()
        f.write(content)
    result = probe_source(str(upload_path))
    result["upload_path"] = str(upload_path)
    return JSONResponse(result)


@app.delete("/api/ingest/upload/{filename:path}")
async def api_delete_upload(filename: str):
    upload_path = UPLOADS_DIR / filename
    if not upload_path.exists():
        raise HTTPException(status_code=404, detail="Upload not found")
    # Prevent path traversal
    if not upload_path.resolve().is_relative_to(UPLOADS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")
    upload_path.unlink()
    return JSONResponse({"deleted": filename})


@app.post("/api/ingest/register")
async def api_register(request: Request):
    body = await request.json()
    source_id = register_source(body, DATA_DIR)
    return JSONResponse({"id": source_id})


@app.post("/api/ingest/build-index/{source_id}")
async def api_build_index(source_id: str):
    try:
        index_path = await asyncio.to_thread(build_index, source_id, DATA_DIR)
        return JSONResponse({"source_id": source_id, "index_file": index_path})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Synonym API routes ---

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
