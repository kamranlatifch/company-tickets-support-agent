"""Cogent Support Chat — customer-facing Streamlit UI."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import authenticate
from config import LIVE_WAIT_SECONDS, MAX_TICKETS_PER_LOGIN, POLL_INTERVAL_SECONDS
from schemas import ChatOutcome, TicketStatus

st.set_page_config(page_title="Cogent Support Chat", page_icon="💬", layout="wide")


def _init_session():
    defaults = {
        "authenticated": False,
        "email": "",
        "role": "",
        "messages": [],
        "login_started_at": "",
        "pending_confirm": None,  # {"query": ..., "reason": ..., "history": ...} awaiting yes/no
        "active_ticket_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _logout():
    for key in ("authenticated", "email", "role", "messages", "login_started_at", "pending_confirm", "active_ticket_id"):
        st.session_state.pop(key, None)


def _login_page():
    st.title("💬 Cogent Support")
    st.caption("Log in to chat with support.")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        user = authenticate(email, password)
        if user and user["role"] == "customer":
            st.session_state.authenticated = True
            st.session_state.email = user["email"]
            st.session_state.role = user["role"]
            st.session_state.messages = []
            st.session_state.login_started_at = datetime.now(timezone.utc).isoformat()
            st.rerun()
        elif user and user["role"] == "admin":
            st.error("Admin accounts use the Admin Dashboard page, not this chat.")
        else:
            st.error("Invalid email or password.")


def _history_text() -> str:
    lines = []
    for msg in st.session_state.messages[-12:]:
        speaker = "Customer" if msg["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {msg['content']}")
    return "\n".join(lines)


@st.fragment(run_every=POLL_INTERVAL_SECONDS)
def _wait_for_admin_reply():
    from tools import get_ticket

    ticket_id = st.session_state.active_ticket_id
    if not ticket_id:
        return
    ticket = get_ticket(ticket_id)
    if ticket is None:
        return

    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(ticket.created_at)).total_seconds()

    if ticket.status == TicketStatus.ANSWERED:
        st.chat_message("assistant").markdown(f"**Support replied:**\n\n{ticket.answer}")
        st.session_state.messages.append({"role": "assistant", "content": f"**Support replied:**\n\n{ticket.answer}"})
        st.session_state.active_ticket_id = None
        st.rerun()
    elif elapsed > LIVE_WAIT_SECONDS:
        st.info("Still working on it — you'll get an email as soon as it's resolved.")
        st.session_state.active_ticket_id = None
    else:
        st.caption(f"Waiting for support… (ticket `{ticket_id}`, checking every {POLL_INTERVAL_SECONDS}s)")


def _handle_confirmation():
    pending = st.session_state.pending_confirm
    st.chat_message("assistant").markdown(
        "This looks like something a specialist should handle — want me to open a support ticket for it?"
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        yes = st.button("Yes, open a ticket", type="primary", key="confirm_yes")
    with col2:
        no = st.button("No, keep trying myself", key="confirm_no")

    if yes:
        from tools import can_create_ticket, create_ticket

        ok, count = can_create_ticket(st.session_state.email, st.session_state.login_started_at)
        if not ok:
            msg = (
                f"You've already got {MAX_TICKETS_PER_LOGIN} open tickets with our team this session — "
                "they'll be with you shortly! I can still try to help in the meantime, though."
            )
            st.chat_message("assistant").markdown(msg)
            st.session_state.messages.append({"role": "assistant", "content": msg})
        else:
            ticket = create_ticket(
                st.session_state.email, pending["query"], _history_text(), pending["reason"]
            )
            st.session_state.active_ticket_id = ticket.id
            msg = f"Done — ticket `{ticket.id}` created. I'll let you know the moment support replies."
            st.chat_message("assistant").markdown(msg)
            st.session_state.messages.append({"role": "assistant", "content": msg})
        st.session_state.pending_confirm = None
        st.rerun()

    if no:
        msg = "No problem — go ahead and ask me anything else, I'll do my best with what I know."
        st.chat_message("assistant").markdown(msg)
        st.session_state.messages.append({"role": "assistant", "content": msg})
        st.session_state.pending_confirm = None
        st.rerun()


def _chat_page():
    with st.sidebar:
        st.subheader("Session")
        st.write(f"**User:** {st.session_state.email}")
        if st.button("Log out"):
            _logout()
            st.rerun()

    st.title("💬 Chat with Support")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.session_state.active_ticket_id:
        _wait_for_admin_reply()

    if st.session_state.pending_confirm:
        _handle_confirmation()
        return

    prompt = st.chat_input("Ask a question...")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    from agents import assess_message
    from policy import decide_outcome
    from rag.answer import prepare_answer_stream, prepare_smalltalk_stream, search_kb
    from tools import get_account

    history = _history_text()
    with st.spinner("Thinking..."):
        assessment = assess_message(prompt, history=history)
        account = get_account(st.session_state.email)
        hits, kb_score = [], None  # small talk skips the KB search and the relevance check
        if not assessment.is_small_talk:
            hits = search_kb(prompt, assessment.summary, st.session_state.messages[:-1])
            kb_score = hits[0]["score"] if hits else 0.0
        outcome, reason = decide_outcome(assessment, account, kb_score)

    if outcome == ChatOutcome.ANSWER:
        with st.chat_message("assistant"):
            if assessment.is_small_talk:
                answer = st.write_stream(prepare_smalltalk_stream(prompt, st.session_state.messages[:-1]))
            else:
                prepared = prepare_answer_stream(prompt, history=st.session_state.messages[:-1], hits=hits)
                answer = st.write_stream(prepared["stream"])
        st.session_state.messages.append({"role": "assistant", "content": answer})
    else:
        st.session_state.pending_confirm = {"query": prompt, "reason": reason}
        st.rerun()


def main():
    _init_session()
    if not st.session_state.authenticated:
        _login_page()
    else:
        _chat_page()


if __name__ == "__main__":
    main()
