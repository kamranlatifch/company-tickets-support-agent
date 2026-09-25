"""Streamlit entry point for the admin dashboard (shows as "Admin Dashboard" in the sidebar).

The actual page lives in support_chat/ui/admin.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from support_chat.ui.admin import main  # noqa: E402

main()
