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
        "(hi, hello, good morning, thanks, ok, bye), or a remark about the assistant itself such as "
        "'you are dumb' or 'you are useless', that contains no question or request; a "
        "greeting followed by a question ('hi, how do I reset my password') is NOT small talk. "
        "Set asks_what_you_cover true when the customer asks which topics, policies or documents you "
        "know about or can help with ('what policies can I ask you about', 'send me the list of "
        "policies you are aware of'), as opposed to asking about the content of one policy. "
        "is_angry describes tone only; a frustrated customer who asks a real question still gets "
        "their question assessed normally. "
        "Set needs_account_data true ONLY when answering requires looking up the customer's own "
        "individual record: 'what is my leave balance', 'my August payslip', 'the status of my loan "
        "application'. A first-person question about a general rule or entitlement is NOT account data, "
        "because the policy answers it the same way for everyone: 'how many sick leaves do I get on "
        "probation', 'what is the maximum loan I can apply for', 'can I take two loans' all have "
        "needs_account_data false. "
        "Set is_urgent true only for a real outage, a blocked workflow, or an explicit deadline ('today', "
        "'ASAP', 'in an hour'); frustration, repeated questions and exclamation marks are not urgency. "
        "Detect anger/frustration separately, "
        "any billing or refund/credit mention with a dollar amount, and any explicit request "
        "to talk to a human or support agent; wants_human is true only when the customer's latest message "
        "asks for a person, never because the assistant itself offered one earlier."
    ),
)


def _prompt(message: str, history: str) -> str:
    return f"Conversation so far:\n{history}\n\nLatest message:\n{message}" if history else message


def assess_message(message: str, history: str = "") -> MessageAssessment:
    return assess_agent.run_sync(_prompt(message, history), model=get_model()).output


async def assess_message_async(message: str, history: str = "") -> MessageAssessment:
    """Same as assess_message, for callers that already run in an event loop (the evals)."""
    return (await assess_agent.run(_prompt(message, history), model=get_model())).output
