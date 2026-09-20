import os
import sys

_api_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _api_root not in sys.path:
    sys.path.insert(0, _api_root)

try:
    from ai.embedding import embed_text, validate_embedding
    from ai.generation import generate_with_fallback, get_provider_manager
    from ai.retrieval import get_similar_documents, hybrid_search, rerank_documents
    from ai.session import build_search_query, ensure_session, get_session_history, save_message
except ImportError:
    from .embedding import embed_text, validate_embedding
    from .generation import generate_with_fallback, get_provider_manager
    from .retrieval import get_similar_documents, hybrid_search, rerank_documents
    from .session import build_search_query, ensure_session, get_session_history, save_message

__all__ = [
    "embed_text",
    "validate_embedding",
    "generate_with_fallback",
    "get_provider_manager",
    "get_similar_documents",
    "hybrid_search",
    "rerank_documents",
    "build_search_query",
    "ensure_session",
    "get_session_history",
    "save_message",
]
