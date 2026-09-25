from pydantic_ai import Agent

from support_chat.agents.llm import get_model
from support_chat.schemas import MessageAssessment

assess_agent = Agent(
    output_type=MessageAssessment,
    retries=2,
    instructions=(
        "You triage Cogent Labs support chat messages. Extract structured fields only. "
        "category MUST be exactly one of: general, billing, technical, feature, complaint, other. "
        "Set confidence high when the message is a general question about company policy or how "
        "something works (the KB covers policies such as leave, loans, medical, hardware, trips, "
        "plus account basics). Follow-ups like 'how much is the maximum?' inherit the topic of the "
        "conversation so far. Lower confidence only for genuinely ambiguous or multi-part requests. "
        "Set is_small_talk true ONLY for a pure greeting, thanks, acknowledgement or goodbye "
        "(hi, hello, good morning, thanks, ok, bye) that contains no question or request; a "
        "greeting followed by a question ('hi, how do I reset my password') is NOT small talk. "
        "Set needs_account_data true ONLY when answering requires looking up the customer's own "
        "individual record: 'what is my leave balance', 'my August payslip', 'the status of my loan "
        "application'. A first-person question about a general rule or entitlement is NOT account data, "
        "because the policy answers it the same way for everyone: 'how many sick leaves do I get on "
        "probation', 'what is the maximum loan I can apply for', 'can I take two loans' all have "
        "needs_account_data false. "
        "Detect urgency (outage, broken workflow, time pressure), anger/frustration, "
        "any billing or refund/credit mention with a dollar amount, and any explicit request "
        "to talk to a human or support agent."
    ),
)


def _prompt(message: str, history: str) -> str:
    return f"Conversation so far:\n{history}\n\nLatest message:\n{message}" if history else message


def assess_message(message: str, history: str = "") -> MessageAssessment:
    return assess_agent.run_sync(_prompt(message, history), model=get_model()).output


async def assess_message_async(message: str, history: str = "") -> MessageAssessment:
    """Same as assess_message, for callers that already run in an event loop (the evals)."""
    return (await assess_agent.run(_prompt(message, history), model=get_model())).output
