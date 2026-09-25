"""Streamlit entry point for the customer chat (deploy with this as the main file).

Streamlit needs this file, and pages/, at the repo root; the actual UI lives in
support_chat/ui/chat.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from support_chat.ui.chat import main  # noqa: E402

main()
