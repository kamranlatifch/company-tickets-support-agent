import os
import shutil
import threading

import chromadb

try:
    from chromadb.api.shared_system_client import SharedSystemClient
except ImportError:  # module path differs across chromadb versions
    SharedSystemClient = None

from support_chat.config import COLLECTION_NAME, INDEX_DIR, ROOT

BUNDLED_INDEX_DIR = ROOT / "index"
_ephemeral_client_instance = None

_lock = threading.RLock()
_persistent = None
_materialized = False


def _on_cloud() -> bool:
    return os.getenv("STREAMLIT_RUNTIME_ENVIRONMENT") == "cloud" or (ROOT / "app.py").as_posix().startswith(
        "/mount/src/"
    )


def bundled_index_available() -> bool:
    return (BUNDLED_INDEX_DIR / "chroma.sqlite3").is_file()


def _collection_metadata() -> dict:
    return {"hnsw:space": "cosine", "hnsw:sync_threshold": 100000}


def _get_ephemeral_client() -> chromadb.EphemeralClient:
    global _ephemeral_client_instance
    if _ephemeral_client_instance is None:
        _ephemeral_client_instance = chromadb.EphemeralClient()
    return _ephemeral_client_instance


def _materialize_bundled_index() -> bool:
    if not BUNDLED_INDEX_DIR.is_dir():
        return False
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if INDEX_DIR.exists() and INDEX_DIR != BUNDLED_INDEX_DIR:
        shutil.rmtree(INDEX_DIR, ignore_errors=True)
    shutil.copytree(BUNDLED_INDEX_DIR, INDEX_DIR)
    return True


def _persistent_client():
    global _persistent
    with _lock:
        if _persistent is None:
            INDEX_DIR.mkdir(parents=True, exist_ok=True)
            _persistent = chromadb.PersistentClient(path=str(INDEX_DIR))
        return _persistent


def _forget_persistent_client() -> None:
    """Drop the cached client (e.g. before the index folder is deleted and rebuilt)."""
    global _persistent
    with _lock:
        _persistent = None
        if SharedSystemClient is not None:
            SharedSystemClient.clear_system_cache()


def get_client():
    global _materialized
    with _lock:
        if _on_cloud():
            if bundled_index_available():
                if not _materialized:  # copy the committed index into the writable temp dir once
                    _forget_persistent_client()
                    _materialize_bundled_index()
                    _materialized = True
                return _persistent_client()
            return _get_ephemeral_client()
        return _persistent_client()


def get_collection():
    client = get_client()
    return client.get_or_create_collection(COLLECTION_NAME, metadata=_collection_metadata())


def reset_and_get_collection():
    """Drop the index and return a fresh empty collection — used by ingest."""
    if _on_cloud() and not bundled_index_available():
        client = _get_ephemeral_client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        return client.create_collection(COLLECTION_NAME, metadata=_collection_metadata())

    with _lock:
        _forget_persistent_client()
        if INDEX_DIR.exists():
            shutil.rmtree(INDEX_DIR)
        client = _persistent_client()
    return client.create_collection(COLLECTION_NAME, metadata=_collection_metadata())


def upsert(ids: list[str], documents: list[str], embeddings: list[list[float]], metadatas: list[dict]):
    col = reset_and_get_collection()
    col.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)


def search(query_embedding: list[float], top_k: int):
    col = get_collection()
    if col.count() == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    return col.query(query_embeddings=[query_embedding], n_results=min(top_k, col.count()))
