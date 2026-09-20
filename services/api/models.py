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
    clean_upsert: Optional[bool] = True


class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class DocumentRenameRequest(BaseModel):
    name: Optional[str] = None
    pdf_name: Optional[str] = None
    category: Optional[Literal["private", "public"]] = None


class OCRPageRequest(BaseModel):
    image_base64: str
    page_num: Optional[int] = 1


class DocumentSummaryRequest(BaseModel):
    document_name: str
    sample_text: str

