# Evals with DeepEval — a walkthrough

Run everything from the repo root.

```bash
python3 -m evals.run routing          # does the gate route each message correctly?   (no judge, ~1 min)
python3 -m evals.run rag              # retrieval + answer quality                     (LLM judge, ~1 min)
python3 -m evals.run drafts           # admin draft replies                            (LLM judge, ~30 s)
python3 -m evals.run all
python3 -m evals.run rag --limit 3 --verbose      # quick check, full DeepEval report
EVAL_JUDGE_MODEL=openai/gpt-4o-mini python3 -m evals.run rag   # try a different judge
```

Results are saved to `evals/results/<suite>.json` (gitignored; one file per suite, overwritten each run) with every
question, the bot's actual answer, and which passages it retrieved, so you can read failures instead of guessing.
Before overwriting, the runner prints how the headline scores moved versus the previous run.

## 1. What an eval is (and why not just try it by hand)

Trying a few questions in the browser finds obvious bugs. It can't tell you whether a prompt change
made things better *overall*, or quietly broke something else. An eval is a fixed set of questions
with known-good answers that you re-run after every change, and a score you can compare.

This project's evals found real bugs that manual testing missed (see "What the evals caught").

## 2. The four ideas in DeepEval

| Idea | In DeepEval | Here |
|---|---|---|
| **Test case** | `LLMTestCase(input, actual_output, expected_output, retrieval_context)` | one question run through the real pipeline |
| **Metric** | an object that scores a test case 0–1 with a threshold | `evals/metrics.py` |
| **Judge** | the LLM that grades, for LLM-based metrics | `evals/judge.py` (OpenRouter) |
| **evaluate()** | scores every test case against every metric | `score()` in `evals/run.py` |

A test case is just data:

- `input` — what the customer asked
- `actual_output` — what *our app* answered (produced by running the real code)
- `expected_output` — the ideal answer, written by you, from the KB (ground truth)
- `retrieval_context` — the KB passages our app retrieved for that question

## 3. The three suites

**routing** — for each message, run the real gate (`support_chat/pipeline.py`) and check ANSWER vs ESCALATE.
Uses a *custom* metric (`RoutingMatchMetric`): the gate is plain code, so plain equality is the right
check. No judge, no cost. Dataset: `evals/datasets/routing.json` — 10 cases, one or two per group (greeting, a rude remark to the bot, "what do you cover?", follow-up,
multi-part, angry-but-valid question, not-in-KB, account data, a refund, a human request). Each dataset is capped at 10 cases to keep runs fast and cheap.

**rag** — for each question, retrieve passages, generate the answer, then grade with four built-in metrics:

| Metric | Question it asks | Needs |
|---|---|---|
| Contextual Recall | Did retrieval fetch everything the ideal answer needs? | expected_output, retrieval_context |
| Contextual Precision | Are the relevant passages ranked above the irrelevant ones? | expected_output, retrieval_context |
| Faithfulness | Is every claim in the answer supported by the retrieved passages? (catches hallucination) | retrieval_context |
| Answer Relevancy | Does the answer address the question, without padding? | input |

Read them as a diagnosis: low **recall/precision** = fix retrieval (chunking, embeddings); low
**faithfulness/relevancy** with good retrieval = fix the answer prompt.

**drafts** — grades the admin's AI-drafted replies with two `GEval` metrics. GEval is the flexible one:
you write the criterion in plain English ("must not promise a refund unless the KB says so") and the
judge scores against it.

## 4. The judge — the part that surprises people

LLM-graded metrics are only as good as the judge.

- DeepEval defaults to OpenAI; we use OpenRouter, so `evals/judge.py` is a small subclass of
  `DeepEvalBaseLLM` with `generate()` / `a_generate()`.
- **Use a different model family than the one being graded.** The app uses Gemini; the default judge is
  `anthropic/claude-haiku-4.5`. A model tends to grade its own style generously.
- **The judge matters.** Same answers, two judges: `gpt-4o-mini` gave answer-relevancy 0.80 with 6 failures
  (mostly false alarms); `claude-haiku-4.5` gave 0.97 with 2. Pick the judge by reading its disagreements.
- **Judges are noisy.** In our runs `gpt-4o-mini` scored a correct answer ("No, employees on probation
  are not eligible") 0.0, claiming it said the opposite. Never trust a failing score without reading the
  answer (that is why results are saved). Treat scores as a signal, look at the trend across changes,
  and use more test cases to average the noise out.

## 5. The workflow: change one thing, re-run, compare

1. Run `python3 -m evals.run all` — note the numbers.
2. Change one thing (a prompt, chunking, a threshold).
3. Re-run. Better overall with nothing broken? Keep it. Otherwise revert.
4. When a bug shows up in real use, add it to a dataset first (so it can never come back), then fix it.

## 6. Adding your own cases

Edit `evals/datasets/*.json`:

- **routing.json** — `{"id", "group", "message", "expected": "ANSWER"|"ESCALATE", "history": null|[{"role","content"}, ...]}`
- **rag.json** — `{"id", "question", "expected_output", "history"}` (`history` is `null` or the earlier
  messages, written into the case; it's there so a bare follow-up like "ok how many max amount?" can be tested). Write `expected_output` from the
  actual KB text, not from memory; a wrong ground truth makes a good answer look bad.
- **drafts.json** — `{"id", "query", "reason"}`

## 7. Gotchas we hit

- **Import order matters.** Importing `deepeval` patches asyncio globally. So `evals/run.py` runs the
  app's pipeline first, *then* imports DeepEval to grade (see the note at the top of `run.py`).
- **Async.** Cases are built concurrently on one asyncio event loop (at most 5 at a time) using the `*_async`
  versions of the app's own functions (`assess_and_route_async`, `draft_ticket_reply_async`); the sync
  search/Chroma calls run in a worker thread. DeepEval then grades them, also concurrently.
- **Cost and time.** The rag suite is 10 cases × ~6 judge calls each; all three suites take ~80 s. Use `--limit N` while iterating.
- **Small datasets are noisy.** 4 draft cases can swing a lot on one bad judge call. Grow them.

## 8. What the evals caught (real bugs, not hypotheticals)

| Found by | Problem | Fix |
|---|---|---|
| routing (90% → 100%) | first-person policy questions ("how many sick leaves do I get on probation?") were flagged as "asks about own account data" and ticketed | assessment prompt now separates a personal record from a general entitlement, with examples |
| rag (recall 0.92 → 1.00) | "medical reimbursement on probation?" retrieved the *sick-leave* rule and answered wrongly; hardware list not found | embed each chunk with its document title; drop title-only chunks |
| rag (relevancy) | answers padded with unrelated details | answer prompt: stay on the question asked |
| drafts (min 0.2 → 0.6+) | for a $300 double-charge complaint the drafter wrote "we have processed a full refund" | drafting prompt: describe next steps as what the team *will* do, never as done |
| running the evals concurrently | shared agent HTTP client failed ~2% of concurrent calls; Chroma client creation raced (10/10 trials failed) | thread-local model per thread; one locked Chroma client created once |

## 9. Tracing (Logfire) — the other half

`support_chat/observability.py` sends traces to Logfire when `LOGFIRE_TOKEN` is set (nothing is sent if it
is blank). Each customer message is one `chat turn` span containing the assessment agent run, the
embedding call, the gate decision (outcome, reason, KB score — never the email address) and the
streamed answer. Evals tell you *whether* it's good; traces show you *what happened* on one specific bad
conversation. Use both.
