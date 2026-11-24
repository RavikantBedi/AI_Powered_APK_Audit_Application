"""Module 3 endpoint: upload a messy file, download a cleaned CSV."""
import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.modules import data_cleanup

logger = logging.getLogger("agency.cleanup")
router = APIRouter()


@router.post("/cleanup")
async def cleanup_file(
    file: UploadFile = File(...),
    provider: str | None = Form(None),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (10 MB limit)")
    try:
        headers, rows = data_cleanup.parse_file(file.filename or "upload.csv", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    llm = {"provider": provider, "api_key": api_key, "model": model} if api_key else None
    col_types, source = data_cleanup.classify_columns(headers, rows, llm)
    cleaned, report = data_cleanup.clean_table(headers, rows, col_types)
    report["column_types"] = col_types
    report["classified_by"] = source
    logger.info("cleaned %s: %s", file.filename, report)

    out_name = (file.filename or "upload").rsplit(".", 1)[0] + "_cleaned.csv"
    return Response(
        content=data_cleanup.to_csv_bytes(headers, cleaned),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Cleanup-Report": json.dumps(report),
        },
    )
