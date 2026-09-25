import streamlit as st
from langgraph.types import Command

from support_chat.auth import authenticate
from support_chat.observability import setup_tracing
from support_chat.schemas import TicketStatus
from support_chat.tools import get_ticket, list_all_tickets, resolve_and_email
from support_chat.workflows.admin_review import build_review_graph


def _init_session():
    defaults = {
        "admin_authenticated": False,
        "admin_email": "",
        "reviewing_ticket_id": None,
        "review_draft": None,  # {"subject": ..., "body": ...} — latest interrupt payload
        "review_done": None,  # set once finalized, holds final subject/body for confirmation
        "review_email_result": None,  # send_resolution_email's result, so it fires once per approval
        "draft_version": 0,  # bumps on every new draft so the text boxes below are recreated, not stale
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_resource
def _get_graph():
    return build_review_graph()


def _login():
    st.title("🛠️ Support Admin")
    with st.form("admin_login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        user = authenticate(email, password)
        if user and user["role"] == "admin":
            st.session_state.admin_authenticated = True
            st.session_state.admin_email = user["email"]
            st.rerun()
        else:
            st.error("Invalid admin credentials.")


def _ticket_list():
    tickets = list_all_tickets()
    open_tickets = [t for t in tickets if t.status == TicketStatus.OPEN]
    answered = [t for t in tickets if t.status == TicketStatus.ANSWERED]

    st.subheader(f"Open ({len(open_tickets)})")
    if not open_tickets:
        st.caption("No open tickets.")
    for t in open_tickets:
        with st.container(border=True):
            st.write(f"**{t.id}** — {t.user_email}")
            st.caption(f"{t.reason} · {t.created_at}")
            st.write(t.query)
            if st.button("Review", key=f"review_{t.id}"):
                st.session_state.reviewing_ticket_id = t.id
                st.session_state.review_draft = None
                st.session_state.review_done = None
                st.session_state.review_email_result = None
                st.rerun(scope="app")

    with st.expander(f"Answered ({len(answered)})"):
        for t in answered:
            st.write(f"**{t.id}** — {t.user_email}")
            st.caption(f"Resolved {t.resolved_at}")
            st.write(t.answer)
            st.divider()


def _set_draft(payload: dict):
    """Show a new draft. Streamlit keeps a keyed widget's old text when its default value
    changes, so the text boxes are keyed by draft_version to force a fresh one."""
    st.session_state.review_draft = payload
    st.session_state.draft_version += 1


def _start_review(ticket_id: str):
    ticket = get_ticket(ticket_id)
    if ticket is None:
        st.error("Ticket not found.")
        return

    graph = _get_graph()
    config = {"configurable": {"thread_id": ticket_id}}
    result = graph.invoke(
        {
            "ticket_id": ticket_id,
            "user_email": ticket.user_email,
            "query": ticket.query,
            "reason": ticket.reason,
            "chat_context": ticket.chat_context,
            "admin_notes": [],
        },
        config=config,
    )
    interrupts = result.get("__interrupt__")
    if interrupts:
        _set_draft(interrupts[0].value)


def _submit(action: str, **payload):
    graph = _get_graph()
    config = {"configurable": {"thread_id": st.session_state.reviewing_ticket_id}}
    result = graph.invoke(Command(resume={"action": action, **payload}), config=config)

    interrupts = result.get("__interrupt__")
    if interrupts:
        _set_draft(interrupts[0].value)
    else:
        st.session_state.review_done = {
            "subject": result.get("final_subject"),
            "body": result.get("final_body"),
        }


def _review_panel():
    ticket_id = st.session_state.reviewing_ticket_id
    st.divider()
    st.subheader(f"Reviewing {ticket_id}")

    if st.session_state.review_draft is None and st.session_state.review_done is None:
        with st.spinner("Drafting a reply..."):
            _start_review(ticket_id)
        st.rerun(scope="app")

    if st.session_state.review_done:
        done = st.session_state.review_done
        # This block re-runs on every Streamlit rerun (including the Back button click),
        # so resolve + send only once and remember the result.
        if st.session_state.review_email_result is None:
            ticket = get_ticket(ticket_id)
            st.session_state.review_email_result = resolve_and_email(
                ticket_id, done["subject"], done["body"], ticket.user_email
            )
        result = st.session_state.review_email_result
        provider = result.get("provider", "The email provider")

        st.success(f"Approved. Ticket {ticket_id} resolved.")
        st.caption("Exactly what was sent to the customer:")
        st.text_input("Subject sent", value=done["subject"], disabled=True, key=f"sent_subject_{ticket_id}")
        st.text_area("Body sent", value=done["body"], height=200, disabled=True, key=f"sent_body_{ticket_id}")
        if result["status"] == "sent":
            st.success(
                f"{provider} accepted the email to {result['to']} (status {result['status_code']}). "
                "That means it was handed off, not that it reached the inbox. If it doesn't "
                f"arrive, check spam and {provider}'s activity/logs page."
            )
        elif result["status"] == "stubbed":
            st.warning(f"No email provider key configured, so nothing was sent to {result['to']}.")
        else:
            st.error(
                f"Ticket resolved, but the email to {result['to']} FAILED "
                f"(status {result.get('status_code')}): {result.get('error')}"
            )
        if st.button("Back to ticket list"):
            st.session_state.reviewing_ticket_id = None
            st.session_state.review_draft = None
            st.session_state.review_done = None
            st.session_state.review_email_result = None
            st.rerun(scope="app")
        return

    draft = st.session_state.review_draft
    if not draft:
        return

    version = st.session_state.draft_version
    st.text_input("Subject", value=draft["draft_subject"], key=f"edit_subject_{version}", disabled=True)
    st.caption("You can edit the reply below; whatever is in the box is what gets sent.")
    body = st.text_area("Draft reply", value=draft["draft_body"], height=260, key=f"edit_body_{version}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve & send", type="primary"):
            _submit("edit", subject=draft["draft_subject"], body=body)
            st.rerun(scope="app")
    with col2:
        if st.button("Give feedback, redraft"):
            st.session_state.show_feedback_box = True

    if st.session_state.get("show_feedback_box"):
        notes = st.text_area("What should change?", key=f"feedback_notes_{version}")
        if st.button("Submit feedback"):
            if notes.strip():
                # send the box's current text too, so the redraft revises it (edits included)
                with st.spinner("Redrafting with your feedback..."):
                    _submit("feedback", notes=notes, body=body)
                st.session_state.show_feedback_box = False
                st.rerun(scope="app")
            else:
                st.warning("Write what should change first.")

    if st.button("Cancel review"):
        st.session_state.reviewing_ticket_id = None
        st.session_state.review_draft = None
        st.session_state.review_done = None
        st.session_state.review_email_result = None
        st.session_state.show_feedback_box = False
        st.rerun(scope="app")


def _dashboard():
    with st.sidebar:
        st.write(f"**Admin:** {st.session_state.admin_email}")
        if st.button("Log out"):
            for key in ("admin_authenticated", "admin_email", "reviewing_ticket_id", "review_draft", "review_done"):
                st.session_state.pop(key, None)
            st.rerun()

    st.title("🛠️ Ticket Dashboard")
    # Auto-refresh the list only while browsing it. During a review the admin is typing and
    # clicking, and a background rerun every few seconds makes those clicks queue behind it
    # (and flashes the "running" indicator). The list refreshes again when they go back.
    poll_every = None if st.session_state.reviewing_ticket_id else 5
    st.fragment(_ticket_list, run_every=poll_every)()

    if st.session_state.reviewing_ticket_id:
        _review_panel()


def main():
    setup_tracing()
    # Must run on every rerun (the entry script is re-executed, imported modules are not).
    st.set_page_config(page_title="Admin Dashboard", page_icon="🛠️", layout="wide")
    _init_session()
    if not st.session_state.admin_authenticated:
        _login()
    else:
        _dashboard()

