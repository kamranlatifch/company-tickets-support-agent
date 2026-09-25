import argparse
import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from support_chat.agents import draft_ticket_reply_async
from support_chat.pipeline import assess_and_route_async
from support_chat.rag.answer import prepare_answer_stream, search_kb
from support_chat.schemas import CustomerAccount
from support_chat.tools import search_kb as admin_search_kb

DATASETS = Path(__file__).parent / "datasets"
RESULTS = Path(__file__).parent / "results"
CONCURRENCY = 5  # how many cases run at the same time while building test cases


@dataclass
class Case:
    """One thing to grade. Becomes a DeepEval LLMTestCase in score()."""

    name: str
    input: str
    actual_output: str
    expected_output: str | None = None
    retrieval_context: list[str] | None = None
    metadata: dict = field(default_factory=dict)

def load(name: str) -> list[dict]:
    return json.loads((DATASETS / f"{name}.json").read_text())


def sample_customer() -> CustomerAccount:
    return CustomerAccount(email="eval@example.com", name="Eval")


async def gather_limited(coroutines):
    gate = asyncio.Semaphore(CONCURRENCY)

    async def limited(coro):
        async with gate:
            return await coro

    return await asyncio.gather(*(limited(c) for c in coroutines))


# ---- suite 1: routing --------------------------------------------------------------------------
async def routing_cases(limit: int | None) -> list[Case]:
    async def build(item: dict) -> Case:
        gate = await assess_and_route_async(item["message"], item["history"] or [])
        return Case(
            name=item["id"],
            input=item["message"],
            actual_output=gate.outcome.name,
            expected_output=item["expected"],
            metadata={"group": item["group"], "reason": gate.reason, "kb_score": gate.kb_score},
        )

    return await gather_limited(build(item) for item in load("routing")[:limit])


def summarize_routing(cases: list[Case]) -> dict:
    groups = defaultdict(lambda: [0, 0])
    failures = []
    for c in cases:
        ok = c.actual_output == c.expected_output
        groups[c.metadata["group"]][0] += ok
        groups[c.metadata["group"]][1] += 1
        if not ok:
            failures.append(f"{c.name}: {c.input!r} -> {c.actual_output} (wanted {c.expected_output}); {c.metadata['reason']}")
    total = sum(g[1] for g in groups.values())
    correct = sum(g[0] for g in groups.values())
    print(f"\nROUTING ACCURACY: {correct}/{total} = {correct / total:.0%}")
    for group, (ok, n) in groups.items():
        print(f"  {group:18} {ok}/{n}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print("  ✗", f)
    return {"accuracy": correct / total, "by_group": {g: f"{a}/{b}" for g, (a, b) in groups.items()}, "failures": failures}


# ---- suite 2: RAG ------------------------------------------------------------------------------
async def rag_cases(limit: int | None) -> list[Case]:
    async def build(item: dict) -> Case:
        history = item["history"] or []
        # same steps as the app: assess (for the context-resolved summary) -> search -> answer
        gate = await assess_and_route_async(item["question"], history)
        hits = gate.hits or await asyncio.to_thread(search_kb, item["question"], gate.assessment.summary, history)
        prepared = await asyncio.to_thread(prepare_answer_stream, item["question"], history, hits)
        answer = await asyncio.to_thread(lambda: "".join(prepared["stream"]))  # the answer streams from a sync client
        return Case(
            name=item["id"],
            input=item["question"],
            actual_output=answer,
            expected_output=item["expected_output"],
            retrieval_context=[h["text"] for h in hits],
            metadata={"sources": [h["label"] for h in hits]},
        )

    return await gather_limited(build(item) for item in load("rag")[:limit])


# ---- suite 3: admin draft replies --------------------------------------------------------------
async def draft_cases(limit: int | None) -> list[Case]:
    async def build(item: dict) -> Case:
        matches = await asyncio.to_thread(admin_search_kb, item["query"])  # exactly what the admin's drafter is given
        draft = await draft_ticket_reply_async(item["query"], matches, sample_customer(), reason=item["reason"])
        return Case(
            name=item["id"],
            input=item["query"],
            actual_output=f"Subject: {draft.subject}\n\n{draft.body}",
            retrieval_context=[m.excerpt for m in matches],
            metadata={"sources": [m.title for m in matches]},
        )

    return await gather_limited(build(item) for item in load("drafts")[:limit])


# ---- scoring + reporting -----------------------------------------------------------------------
def score(cases: list[Case], make_metrics, verbose: bool, show_failures: bool = True) -> dict:
    # deepeval (and evals.judge / evals.metrics, which import it) are imported here, not at the top of the
    # file: importing deepeval patches asyncio globally, which breaks the concurrent agent calls made
    # while the test cases are built. So this only happens after that phase is finished.
    from deepeval import evaluate
    from deepeval.evaluate.configs import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
    from deepeval.test_case import LLMTestCase

    from evals.judge import JUDGE_MODEL

    test_cases = [LLMTestCase(**vars(c)) for c in cases]
    result = evaluate(
        test_cases=test_cases,
        metrics=make_metrics(),
        async_config=AsyncConfig(run_async=True, max_concurrent=5),
        display_config=DisplayConfig(print_results=verbose, show_indicator=True, inspect_after_run=False),
        cache_config=CacheConfig(write_cache=False, use_cache=False),
        error_config=ErrorConfig(ignore_errors=True),  # one bad judge call shouldn't sink the whole run
    )
    per_metric = defaultdict(list)
    failures = []
    for tr in result.test_results:
        for md in tr.metrics_data or []:
            per_metric[md.name].append(md.score if md.score is not None else 0.0)
            if not md.success:
                reason = (md.reason or md.error or "").replace("\n", " ")
                failures.append(f"{tr.name} · {md.name} = {md.score}: {reason[:230]}")
    print(f"\nAVERAGE SCORE PER METRIC  ({len(cases)} test cases, judge = {JUDGE_MODEL})")
    summary = {}
    for name, scores in per_metric.items():
        summary[name] = round(sum(scores) / len(scores), 3)
        print(f"  {name:32} {summary[name]:.2f}   (min {min(scores):.2f})")
    if failures and show_failures:
        print(f"\nBelow threshold ({len(failures)}):")
        for f in failures:
            print("  ✗", f)
    inspect = [
        {"name": c.name, "input": c.input, "actual_output": c.actual_output, "sources": c.metadata.get("sources")}
        for c in cases
    ]
    return {"averages": summary, "below_threshold": failures, "cases": inspect}


def _headline(payload: dict) -> dict:
    """The numbers worth comparing between runs."""
    return {"accuracy": payload["accuracy"]} if "accuracy" in payload else dict(payload.get("averages", {}))


def save(suite: str, payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{suite}.json"
    if path.exists():
        before, now = _headline(json.loads(path.read_text())), _headline(payload)
        moved = [f"    {name}: {before[name]:.2f} -> {value:.2f} ({value - before[name]:+.2f})" for name, value in now.items() if name in before]
        if moved:
            print("\n  vs previous run:")
            print("\n".join(moved))
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"\nsaved -> evals/results/{suite}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evals: routing | rag | drafts | all")
    parser.add_argument("suite", choices=["routing", "rag", "drafts", "all"])
    parser.add_argument("--limit", type=int, help="only the first N cases of each suite (quick check)")
    parser.add_argument("--verbose", action="store_true", help="print DeepEval's full per-case report")
    args = parser.parse_args()
    suites = ["routing", "rag", "drafts"] if args.suite == "all" else [args.suite]

    def routing_metrics():
        from evals.metrics import RoutingMatchMetric

        return [RoutingMatchMetric()]

    def rag_metric_set():
        from evals.judge import OpenRouterJudge
        from evals.metrics import rag_metrics

        return rag_metrics(OpenRouterJudge())

    def draft_metric_set():
        from evals.judge import OpenRouterJudge
        from evals.metrics import draft_metrics

        return draft_metrics(OpenRouterJudge())

    builders = {"routing": routing_cases, "rag": rag_cases, "drafts": draft_cases}

    # Phase 1: run the app's real pipeline for every suite, concurrently, BEFORE deepeval gets imported.
    async def build_all():
        built, seconds = {}, {}
        for suite in suites:
            started = time.perf_counter()
            print(f"building {suite} cases (running the real pipeline)...")
            built[suite] = await builders[suite](args.limit)
            seconds[suite] = round(time.perf_counter() - started, 1)
        return built, seconds

    built, build_seconds = asyncio.run(build_all())

    # Phase 2: grade them with DeepEval.
    for suite in suites:
        started = time.perf_counter()
        cases = built[suite]
        print(f"\n===== {suite} =====")
        if suite == "routing":
            summary = summarize_routing(cases)
            score(cases, routing_metrics, args.verbose, show_failures=False)  # DeepEval + our custom metric
        elif suite == "rag":
            summary = score(cases, rag_metric_set, args.verbose)
        else:
            summary = score(cases, draft_metric_set, args.verbose)
        summary["seconds"] = {"build": build_seconds[suite], "grade": round(time.perf_counter() - started, 1)}
        save(suite, summary)


if __name__ == "__main__":
    main()
