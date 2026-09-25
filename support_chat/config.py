import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # repo root (this file is support_chat/config.py)
load_dotenv(ROOT / ".env")


def _resolve_index_dir() -> Path:
    override = os.getenv("CHAT_INDEX_DIR")
    if override:
        return Path(override)
    # Streamlit Cloud mounts the repo read-only under /mount/src — same
    # workaround as role-rag-app: copy the committed index to a writable tmp dir.
    on_cloud = Path("/mount/src").is_dir() or os.getenv("STREAMLIT_RUNTIME_ENVIRONMENT") == "cloud"
    if on_cloud:
        return Path(tempfile.gettempdir()) / "cogent-support-index"
    return ROOT / "index"


# LLM / embeddings (OpenRouter)
API_KEY = os.getenv("COGENT_OPRNROUTER_KEY", "")
BASE_URL = "https://openrouter.ai/api/v1"
MODEL = os.getenv("GEMINI_MODEL", "google/gemini-2.5-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")

# Turso
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

# Logfire tracing (optional: blank token = nothing is sent anywhere)
LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN", "")

# Brevo (email on ticket resolution)
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.getenv("BREVO_FROM_EMAIL", "")
BREVO_FROM_NAME = os.getenv("BREVO_FROM_NAME", "Cogent Support")

# Policy
REFUND_APPROVAL_THRESHOLD_USD = float(os.getenv("REFUND_APPROVAL_THRESHOLD_USD", "50"))
MAX_TICKETS_PER_LOGIN = int(os.getenv("MAX_TICKETS_PER_LOGIN", "2"))
# The model's self-rated confidence is noisy (in-KB questions scored 0.3-0.5, out-of-KB
# ones 0.8-0.9 in testing), so it's only a backstop. The real "does the KB cover this"
# check is the best retrieval score: off-topic questions scored <=0.34, in-KB >=0.40.
KB_CONFIDENCE_MIN = float(os.getenv("KB_CONFIDENCE_MIN", "0.25"))
KB_MIN_RETRIEVAL_SCORE = float(os.getenv("KB_MIN_RETRIEVAL_SCORE", "0.38"))

# Paths
DATA_DIR = ROOT / "data"
KB_DIR = DATA_DIR / "kb"
INDEX_DIR = _resolve_index_dir()
USERS_FILE = DATA_DIR / "users.yaml"

COLLECTION_NAME = "support_kb"
TOP_K = 4
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MAX_HISTORY_TURNS = 6

# Wait-for-admin polling (user's chat, while a ticket is fresh)
LIVE_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 3
