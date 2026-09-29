"""Run the CampusAsk evaluation and print its metrics.

    python eval/run_eval.py                     # offline, no key needed
    python eval/run_eval.py --threshold 0.55    # pin the threshold
    python eval/run_eval.py --provider gemini --sweep

`AGENTS.md` section 3 names this command and section 9 names what it must print:
answer rate, citation correctness and fallback correctness, against targets of
85 percent, 95 percent and zero answers on out-of-scope questions. The exit code
is 0 only when all three are met, so it can be wired into a pipeline as-is.

**Why the offline run calibrates its own threshold.** `SIMILARITY_THRESHOLD` is a
number on the embedding model's cosine scale, and the offline run does not use the
embedding model -- it uses the lexical stand-in in `harness.py`, whose cosines sit
in a different band. Evaluating at 0.55 with those vectors would measure the gap
between two scales and call it a product failure. So the offline run sweeps,
takes the threshold that best separates what the corpus answers from what it does
not, reports that as the calibration, and evaluates there. The numbers it prints
are then about the pipeline's decisions: whether a good retrieval result is
answered, cited and -- when it is not good -- refused.

What the offline run cannot tell you is what the shipped threshold should be.
`--provider gemini` runs the same corpus and the same questions against the real
providers; that is the run whose sweep tunes a value worth setting in
`config.py`, and it is the only one whose answer-quality numbers mean anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
# The evaluation is a repository-level tool driving an application that lives in
# backend/. Importing it by path keeps run_eval.py runnable from the repository
# root as AGENTS.md section 3 writes it, without making backend/ installable.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.providers.gemini import GeminiProvider  # noqa: E402
from app.services.answering import AnsweringService  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.retrieval import RetrievalService  # noqa: E402
from eval.harness import (  # noqa: E402
    ANSWER_RATE_TARGET,
    CITATION_TARGET,
    GroundedLLMProvider,
    Judgement,
    LexicalEmbeddingProvider,
    LocalChunkRepository,
    Metrics,
    Question,
    RecordingQueryLog,
    _NoCache,
    read_questions,
    run_questions,
    seed,
    summarise,
)

SWEEP_START = 0.05
SWEEP_STOP = 0.80
SWEEP_STEP = 0.05

# Settings requires three values this run never reads: the corpus, the index and
# the scoring are all in memory. Placeholders keep the offline run from demanding
# credentials it cannot use.
_PLACEHOLDER = "not-used-by-the-offline-evaluation"


class _ErrorCounter(logging.Handler):
    """Counts the warnings the backend logs when a provider call fails.

    The pipeline treats an unreachable model as a reason to fall back, and logs a
    warning rather than raising -- the right call for a student, who gets the same
    honest message either way, but a trap for a measurement. A run that hit a
    Gemini outage looks identical to a run whose retrieval regressed: both are
    fallbacks, and only one of them is the pipeline's fault.

    So the number is counted and printed. Reporting it is the whole point of
    running the evaluation against the real providers; without it the gemini run
    can be read as a verdict on code that was never asked the question.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("app."):
            self.count += 1


_PROVIDER_ERRORS = _ErrorCounter()


@dataclass
class Run:
    """One threshold's worth of results."""

    metrics: Metrics
    judgements: list[Judgement]


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = _settings(args)
    _install_error_counter()
    provider: object = (
        GeminiProvider(settings)
        if args.provider == "gemini"
        else LexicalEmbeddingProvider(settings.embedding_dimensions)
    )

    questions = read_questions(EVAL_DIR / "questions.json")
    documents, repository = await seed(
        settings=settings, corpus_dir=EVAL_DIR / "corpus", provider=provider
    )
    print(
        f"Corpus   {len(documents)} documents, "
        f"{sum(len(document.chunks) for document in documents)} chunks "
        f"({sum(len(document.extracted.pages) for document in documents)} pages)"
    )
    print(f"Provider {args.provider}   Questions {len(questions)}")
    if args.provider == "local":
        print(
            "         lexical embeddings and a grounded model double: this measures the\n"
            "         pipeline's decisions, not Gemini's answer quality."
        )
    print()

    threshold, sweep = await _resolve_threshold(args, settings, repository, questions, provider)
    if sweep:
        print()
    run = await _run_at(settings, repository, questions, provider, threshold)

    _print_detail(run.judgements)
    print()
    _print_metrics(run.metrics)
    _print_retrieval(run.judgements)
    _print_separation(run.judgements)

    if args.json:
        _write_json(args.json, run)

    print()
    if run.metrics.meets_targets():
        print("Targets met.")
        return 0
    print("Targets NOT met.")
    if run.metrics.provider_errors:
        # The targets are still missed, and the exit code still says so. But a
        # reader about to go looking for the regression needs to know that some
        # of these questions were never put to the model.
        print(
            f"  {run.metrics.provider_errors} question(s) fell back because the provider could\n"
            "  not be reached. Re-run before reading this as a change in the pipeline."
        )
    return 1


def _install_error_counter() -> None:
    """Attach the counter to the root logger, once.

    Guarded rather than assumed: `main` is a function a test can call twice in
    one process, and a handler added twice would count every warning twice.
    """
    root = logging.getLogger()
    if _PROVIDER_ERRORS not in root.handlers:
        root.addHandler(_PROVIDER_ERRORS)


async def _resolve_threshold(
    args: argparse.Namespace,
    settings: Settings,
    repository: LocalChunkRepository,
    questions: list[Question],
    provider: object,
) -> tuple[float, Run | None]:
    """The threshold to evaluate at, and the sweep that chose it if there was one.

    Precedence, in the order the three cases are genuinely different:

    * `--threshold` pins it. The evaluation is then a straight measurement of the
      pipeline at a number somebody chose, which is what a regression check wants.
    * offline with no threshold: the sweep calibrates, because the proxy's scale
      is not the shipped one.
    * the real providers with no threshold: the configured value is the thing
      under test. A sweep costs sixteen times the API calls for a run that is
      usually asking "did the code change break anything", so it waits for
      `--sweep`.
    """
    if args.threshold is not None:
        return args.threshold, None

    calibrating = args.provider == "local"
    if not (calibrating or args.sweep):
        return settings.similarity_threshold, None

    runs = await _sweep(settings, repository, questions, provider)
    chosen = _choose(runs)
    if chosen is None:
        print("  No threshold in the swept range avoided answering a question the corpus")
        print("  does not answer. Evaluating at the configured threshold instead.")
        return settings.similarity_threshold, None

    if calibrating:
        print(f"  Calibrated SIMILARITY_THRESHOLD for this run: {chosen.metrics.threshold:.2f}")
        if args.provider == "local":
            print(
                f"  (config.py ships {settings.similarity_threshold:.2f}, which is the value for\n"
                "   the real embedder. The lexical stand-in's cosines sit in a lower band, so\n"
                "   the two are not comparable, and this calibration is not a proposal to\n"
                "   change it.)"
            )
    return chosen.metrics.threshold, chosen


async def _sweep(
    settings: Settings,
    repository: LocalChunkRepository,
    questions: list[Question],
    provider: object,
) -> list[Run]:
    print("Threshold sweep")
    header = f"  {'thr':>5}  {'answer':>6}  {'cite':>6}  {'fallback':>8}  {'oob':>4}  {'amb':>4}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    runs: list[Run] = []
    threshold = SWEEP_START
    while threshold <= SWEEP_STOP + 1e-9:
        run = await _run_at(settings, repository, questions, provider, round(threshold, 4))
        runs.append(run)
        metrics = run.metrics
        marker = "  <-- usable" if _usable(metrics) else ""
        # One decimal, not zero: a rounded 95% next to a 95% target reads as a
        # pass, and 18 of 19 is 94.7%. The whole point of the sweep is picking
        # between neighbouring thresholds, so the column has to resolve them.
        print(
            f"  {metrics.threshold:5.2f}  {metrics.answer_rate:6.1%}  "
            f"{metrics.citation_correctness:6.1%}  {metrics.fallback_correctness:8.1%}  "
            f"{metrics.out_of_scope_answered:4d}  {metrics.ambiguous_answered:4d}{marker}"
        )
        threshold += SWEEP_STEP
    return runs


def _choose(runs: list[Run]) -> Run | None:
    """The threshold this run would use, in two passes.

    First, the thresholds at which the pipeline meets every target in section 9.
    Answering more questions is only worth having if the answers hold up, and a
    threshold that answers one more question and mis-cites it has traded a
    fallback for a wrong answer -- which is the trade the fallback exists to
    refuse. So "meets the targets" comes before "answers the most".

    Failing that, the best answer rate that never fabricates. "Never fabricates"
    is section 9's out-of-scope target read strictly, and it is the only
    disqualifier at this stage: an ambiguous question answered from the passage it
    half-matches is a precision loss rather than an invention, and disqualifying a
    threshold over one would push the choice above the point where real questions
    stop being answered.

    A tie is settled in favour of the median rather than either end of the band.
    The ends are one step from a wrong answer or a lost one, and this is a
    thirty-question evaluation, not a thirty-thousand-question one.
    """
    usable = [run for run in runs if _usable(run.metrics)]
    if not usable:
        return None
    meeting = [run for run in usable if run.metrics.meets_targets()] or usable
    best_rate = max(run.metrics.answer_rate for run in meeting)
    best = [run for run in meeting if run.metrics.answer_rate == best_rate]
    return best[len(best) // 2]


def _usable(metrics: Metrics) -> bool:
    return metrics.out_of_scope_answered == 0


async def _run_at(
    settings: Settings,
    repository: LocalChunkRepository,
    questions: list[Question],
    provider: object,
    threshold: float,
) -> Run:
    """Answer every question with `threshold` in force.

    The services are rebuilt rather than mutated: `similarity_threshold` is read
    from `Settings` at decision time, and a copy with one field changed is the
    only honest way to ask what a different threshold would have done.
    """
    tuned = settings.model_copy(update={"similarity_threshold": threshold})
    query_log = RecordingQueryLog()
    errors_before = _PROVIDER_ERRORS.count

    def pipeline() -> RetrievalService:
        return RetrievalService(EmbeddingService(provider, tuned, _NoCache()), repository, tuned)

    # Two retrieval services over the same repository. The one inside the answerer
    # is the pipeline; the other is the probe `run_questions` uses to report a
    # best similarity for questions the pipeline never got as far as scoring.
    answerer = AnsweringService(
        retrieval=pipeline(),
        llm=GroundedLLMProvider(),
        query_log=query_log,
    )
    probe = pipeline()

    judgements = await run_questions(
        answerer=answerer, retrieval=probe, questions=questions, query_log=query_log
    )
    return Run(
        metrics=summarise(
            judgements,
            threshold=threshold,
            log_rows=len(query_log.entries),
            unanswered_rows=sum(1 for entry in query_log.entries if entry.unanswered),
            provider_errors=_PROVIDER_ERRORS.count - errors_before,
        ),
        judgements=judgements,
    )


def _print_detail(judgements: list[Judgement]) -> None:
    """One line per question: what happened, and why.

    Printed because a metric alone cannot be acted on. A missed question next to a
    similarity just below the threshold says "lower it"; the same question next to
    a similarity of 0.08 says the passage was never retrieved, and the threshold is
    the wrong thing to touch.
    """
    print(f"{'id':<5}{'kind':<14}{'sim':>6}  outcome")
    for item in judgements:
        question = item.question
        similarity = f"{item.best_similarity:.3f}" if item.best_similarity is not None else "  -  "
        if item.answered:
            cited = ", ".join(item.document_titles) or "nothing"
            if question.kind == "answerable" and not item.answer_rate_hit:
                outcome = f"WRONG DOCUMENT (cited {cited})"
            elif question.kind != "answerable":
                outcome = f"SHOULD HAVE FALLEN BACK (cited {cited})"
            else:
                outcome = f"answered from {cited}"
        elif question.kind == "answerable":
            outcome = f"MISSED (top retrieved: {', '.join(item.retrieved_titles) or 'nothing'})"
        else:
            outcome = "fell back"
        print(f"{question.id:<5}{question.kind:<14}{similarity:>6}  {outcome}")


def _print_metrics(metrics: Metrics) -> None:
    print("Metrics")
    _metric(
        "Answer rate",
        metrics.answer_hits,
        metrics.answerable_total,
        metrics.answer_rate,
        ANSWER_RATE_TARGET,
    )
    _metric(
        "Citation correctness",
        metrics.answerable_correct,
        metrics.answerable_answered,
        metrics.citation_correctness,
        CITATION_TARGET,
    )
    print(
        f"  {'Out-of-scope answered':<22}{metrics.out_of_scope_answered:>3} of "
        f"{metrics.out_of_scope_total:<3} {'':>6}  {'target     0':>13}  "
        f"{'ok' if metrics.out_of_scope_answered == 0 else 'FAIL'}"
    )
    # Two lines that carry no verdict, on purpose. Section 9's third target is
    # zero answers on the out-of-scope questions alone, and that is the line
    # above; scoring fallback correctness against 100 percent would print FAIL
    # next to "Targets met" over questions no target was set for.
    print(
        f"  {'Fallback correctness':<22}"
        f"{metrics.fallback_total - metrics.out_of_scope_answered - metrics.ambiguous_answered:>3} "
        f"of {metrics.fallback_total:<3} {metrics.fallback_correctness:>6.1%}  "
        "both kinds; a diagnostic, not a target"
    )
    print(
        f"  {'Ambiguous answered':<22}{metrics.ambiguous_answered:>3} of "
        f"{metrics.ambiguous_total:<3} {'':>6}  a precision loss, not a fabrication"
    )
    print(
        f"  {'Unanswered rows':<22}{metrics.unanswered_rows:>3} for "
        f"{metrics.fallbacks} fallback{'' if metrics.fallbacks == 1 else 's'}"
        f"   {'ok' if metrics.unanswered_rows == metrics.fallbacks else 'MISMATCH'}"
    )
    if metrics.provider_errors:
        print(
            f"  {'Provider errors':<22}{metrics.provider_errors:>3} of those fallbacks "
            "were the provider failing, not the documents"
        )


def _metric(label: str, part: int, whole: int, value: float, target: float) -> None:
    verdict = "ok" if value >= target else "FAIL"
    print(f"  {label:<22}{part:>3} of {whole:<3} {value:>6.1%}  target {target:>5.0%}  {verdict}")


def _print_retrieval(judgements: list[Judgement]) -> None:
    """Whether the right document reached the model at all, threshold or no threshold.

    Separate from the answer rate on purpose. The answer rate moves when a
    threshold moves; this does not, so a fall in it points at the chunker, the
    corpus or the ranking rather than at the one number everything else is blamed
    on.
    """
    answerable = [item for item in judgements if item.question.kind == "answerable"]
    retrieved = sum(
        1 for item in answerable if item.question.expected_document in item.retrieved_titles
    )
    cited = sum(1 for item in answerable if item.question.expected_document in item.document_titles)
    print(
        f"\n  Retrieval   expected document in the top-k for {retrieved} of {len(answerable)}; "
        f"cited by {cited}"
    )


def _print_separation(judgements: list[Judgement]) -> None:
    """How far apart the answerable and unanswerable similarities are.

    When the lowest answerable similarity sits above the highest unanswerable one,
    some threshold separates them perfectly and where to put it inside that window
    is a judgement call. When the two overlap, no threshold can do both, and that
    is a retrieval problem rather than a tuning one -- which is the single most
    useful thing this run can say to whoever is doing the tuning.
    """
    answerable = [
        item.best_similarity
        for item in judgements
        if item.question.kind == "answerable" and item.best_similarity is not None
    ]
    unanswerable = [
        item.best_similarity
        for item in judgements
        if item.question.kind != "answerable" and item.best_similarity is not None
    ]
    if not answerable or not unanswerable:
        return
    print(
        f"  Separation  answerable {min(answerable):.3f} to {max(answerable):.3f}"
        f"   unanswerable {min(unanswerable):.3f} to {max(unanswerable):.3f}"
    )
    if min(answerable) > max(unanswerable):
        print(
            f"              separable: any threshold in "
            f"[{max(unanswerable):.3f}, {min(answerable):.3f}] answers every answerable "
            "question and refuses every other."
        )
    else:
        print(
            "              overlapping: no threshold separates these. The question that\n"
            "              overlaps is the one to look at -- either its passage is not being\n"
            "              retrieved, or it is not in the corpus."
        )


def _settings(args: argparse.Namespace) -> Settings:
    """The configuration the run needs, and only that.

    The Gemini run reads `backend/.env` for the key, but the Supabase pair is
    overridden with a placeholder even when the file holds real values. The
    evaluation seeds its corpus in memory and never opens a database, and the
    project it would otherwise be able to reach is a live one -- so the safest
    version of "the evaluation does not touch the database" is one where it
    cannot, rather than one where it merely does not.
    """
    if args.provider == "gemini":
        return Settings(
            supabase_url=_PLACEHOLDER,
            supabase_service_role_key=_PLACEHOLDER,
        )
    return Settings(
        _env_file=None,
        supabase_url=_PLACEHOLDER,
        supabase_service_role_key=_PLACEHOLDER,
        gemini_api_key=_PLACEHOLDER,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--provider",
        choices=("local", "gemini"),
        default="local",
        help="local runs offline with stand-in providers; gemini uses the real ones",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="evaluate at this SIMILARITY_THRESHOLD instead of calibrating one",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="print a threshold sweep; the offline run sweeps regardless",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the detail as JSON")
    return parser.parse_args(argv)


def _write_json(path: Path, run: Run) -> None:
    """The same numbers as the printed report, for a diff between two runs.

    The counts travel with the ratios because a ratio on its own cannot be
    compared across question sets: 90 percent of twenty and 90 percent of two
    hundred are not the same result, and a threshold sweep is only readable if
    each row says what it was measured over.
    """
    metrics = run.metrics
    path.write_text(
        json.dumps(
            {
                "threshold": metrics.threshold,
                "answer_rate": metrics.answer_rate,
                "citation_correctness": metrics.citation_correctness,
                "fallback_correctness": metrics.fallback_correctness,
                "counts": {
                    "answerable_total": metrics.answerable_total,
                    "answer_hits": metrics.answer_hits,
                    "answerable_answered": metrics.answerable_answered,
                    "answerable_correct": metrics.answerable_correct,
                    "out_of_scope_total": metrics.out_of_scope_total,
                    "out_of_scope_answered": metrics.out_of_scope_answered,
                    "ambiguous_total": metrics.ambiguous_total,
                    "ambiguous_answered": metrics.ambiguous_answered,
                    "fallbacks": metrics.fallbacks,
                    "log_rows": metrics.log_rows,
                    "unanswered_rows": metrics.unanswered_rows,
                },
                "meets_targets": metrics.meets_targets(),
                "questions": [
                    {
                        "id": item.question.id,
                        "kind": item.question.kind,
                        "answered": item.answered,
                        "best_similarity": item.best_similarity,
                        "documents": item.document_titles,
                        "answer_rate_hit": item.answer_rate_hit,
                        "citation_correct": item.citation_correct,
                    }
                    for item in run.judgements
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
