
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from support_chat.agents import draft_ticket_reply
from support_chat.tools import get_account, search_kb


class ReviewState(TypedDict):
    ticket_id: str
    user_email: str
    query: str
    reason: str
    chat_context: str
    draft_subject: str
    draft_body: str
    admin_notes: list[str]
    final_subject: str | None
    final_body: str | None


def _gather_and_draft(state: ReviewState) -> dict:
    kb_matches = search_kb(state["query"])
    account = get_account(state["user_email"])
    notes = "\n".join(state.get("admin_notes") or [])
    draft = draft_ticket_reply(
        state["query"],
        kb_matches,
        account,
        reason=state.get("reason", ""),
        chat_context=state.get("chat_context", ""),
        admin_notes=notes or None,
        previous_draft=state.get("draft_body") if notes else None,
    )
    return {
        "draft_subject": draft.subject,
        "draft_body": draft.body,
    }


def _await_admin(state: ReviewState) -> Command[Literal["gather_and_draft", "finalize"]]:
    decision = interrupt(
        {
            "draft_subject": state["draft_subject"],
            "draft_body": state["draft_body"],
        }
    )
    action = decision.get("action")
    if action == "approve":
        return Command(
            goto="finalize",
            update={"final_subject": state["draft_subject"], "final_body": state["draft_body"]},
        )
    if action == "edit":
        return Command(
            goto="finalize",
            update={
                "final_subject": decision.get("subject", state["draft_subject"]),
                "final_body": decision["body"],
            },
        )
    if action == "feedback":
        notes = list(state.get("admin_notes") or [])
        notes.append(decision["notes"])
        return Command(
            goto="gather_and_draft",
            # the admin's current text (may include manual edits) becomes the base to revise
            update={"admin_notes": notes, "draft_body": decision.get("body") or state["draft_body"]},
        )
    raise ValueError(f"Unknown admin action: {action!r}")


def _finalize(state: ReviewState) -> dict:
    return {}


def build_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("gather_and_draft", _gather_and_draft)
    graph.add_node("await_admin", _await_admin)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("gather_and_draft")
    graph.add_edge("gather_and_draft", "await_admin")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=MemorySaver())
