# services/api/models.py — Pydantic request/response models
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


class ChunkModel(BaseModel):
    text: str
    pdf_name: Optional[str] = None
    category: Literal["private", "public"] = "public"
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None


class EmbedUpsertRequest(BaseModel):
    chunks: List[ChunkModel]


class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class DocumentRenameRequest(BaseModel):
    name: Optional[str] = None
    pdf_name: Optional[str] = None
    category: Optional[Literal["private", "public"]] = None
