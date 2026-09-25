
from deepeval.metrics import (
    AnswerRelevancyMetric,
    BaseMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase, SingleTurnParams

from evals.judge import OpenRouterJudge


class RoutingMatchMetric(BaseMetric):
    """1.0 if the gate's outcome (ANSWER / ESCALATE) equals the expected one, else 0.0."""

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True

    @property
    def __name__(self) -> str:
        return "Routing Match"

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        got, want = test_case.actual_output, test_case.expected_output
        self.score = 1.0 if got == want else 0.0
        self.success = self.score >= self.threshold
        gate_reason = (test_case.metadata or {}).get("reason", "")
        self.reason = f"expected {want}, got {got}" + (f" — gate said: {gate_reason}" if gate_reason else "")
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)


def rag_metrics(judge: OpenRouterJudge) -> list[BaseMetric]:
    return [
        ContextualRecallMetric(threshold=0.7, model=judge),  # did retrieval fetch what the ideal answer needs?
        ContextualPrecisionMetric(threshold=0.5, model=judge),  # are the relevant passages ranked first?
        FaithfulnessMetric(threshold=0.8, model=judge),  # is every claim in the answer supported by the context?
        AnswerRelevancyMetric(threshold=0.7, model=judge),  # does the answer address the question?
    ]


def draft_metrics(judge: OpenRouterJudge) -> list[BaseMetric]:
    return [
        GEval(
            name="No unsupported promises",
            criteria=(
                "The reply must not promise, approve or imply a refund, credit, loan approval, exception or "
                "deadline unless the knowledge base context explicitly states it, and must not invent "
                "policy details. If the knowledge base does not cover the request, the reply should say a "
                "team member will follow up rather than guess."
            ),
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.RETRIEVAL_CONTEXT],
            threshold=0.7,
            model=judge,
        ),
        GEval(
            name="Professional and actionable",
            criteria=(
                "The reply is polite and professional, acknowledges the customer's actual issue, and tells "
                "them a concrete next step or what will happen next."
            ),
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=judge,
        ),
    ]
