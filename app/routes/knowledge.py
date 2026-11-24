"""Stage 8 endpoints: per-client document knowledge base for RAG grounding."""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.modules import knowledge_base

logger = logging.getLogger("agency.knowledge")
router = APIRouter(prefix="/clients/{client_id}/knowledge")


def _require_client(client_id: int, db: Session) -> None:
    if db.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")


@router.post("")
async def upload_document(client_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_client(client_id, db)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (15 MB limit)")
    try:
        chunks_added = knowledge_base.add_documents(client_id, file.filename or "upload.txt", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"client_id": client_id, "filename": file.filename, "chunks_added": chunks_added}


@router.get("")
def list_documents(client_id: int, db: Session = Depends(get_db)):
    _require_client(client_id, db)
    return {"sources": knowledge_base.list_sources(client_id)}


@router.delete("/{source}")
def delete_document(client_id: int, source: str, db: Session = Depends(get_db)):
    _require_client(client_id, db)
    removed = knowledge_base.delete_source(client_id, source)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No document '{source}' for this client")
    return {"client_id": client_id, "source": source, "chunks_removed": removed}


@router.get("/search")
def search_preview(client_id: int, q: str, db: Session = Depends(get_db)):
    """Debug/demo endpoint: see what the RAG retriever would return for a query."""
    _require_client(client_id, db)
    chunks = knowledge_base.retrieve(client_id, q)
    return {
        "query": q,
        "results": [{"source": c.source, "score": round(c.score, 4), "text": c.text} for c in chunks],
    }
