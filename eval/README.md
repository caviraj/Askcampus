# Evaluation

`AGENTS.md` section 5 step 6 asks for an evaluation; section 9 gives it numbers to reach:

> Target: answer rate ≥ 85%, citation correctness ≥ 95%, zero answers on out-of-scope questions.

```bash
python eval/run_eval.py                          # offline; no key, no database, no network
python eval/run_eval.py --provider gemini        # the real embedder and the real model
python eval/run_eval.py --json run.json          # the same numbers, per question
python eval/run_eval.py --provider gemini --sweep   # a threshold sweep
```

It exits `0` when all three targets are met and `1` when one is missed, so it can gate a pipeline.
`backend/tests/test_eval_targets.py` runs the offline evaluation and asserts that exit code, which is
what makes the targets a regression test rather than a number in a report.

## What is in here

| File | What it holds |
|---|---|
| `questions.json` | 30 questions: 20 answerable, 5 out-of-scope, 5 ambiguous |
| `corpus.json` | the manifest — each document's title, file and category |
| `corpus/` | six plain-text college documents |
| `harness.py` | the pipeline under test, the provider doubles, and the metrics |
| `run_eval.py` | the command-line runner and the report |

The corpus is synthetic and small — six documents (`Examination Handbook 2026-27`, `Admission
Brochure 2026`, `Academic Regulations`, `Campus Directory`, `Events Calendar 2026-27`, `General
Notices`), one per category, with page markers so page numbers are real rather than invented. It is
committed as text so a reader can check any answer by hand.

Each answerable question names three things:

- **`expected_document`** — the title the citation must carry.
- **`expected_section`** — a heading that must exist in that document. Asserted by a test, so a
  renamed heading fails loudly instead of silently weakening the check.
- **`expected_terms`** — a phrase that must appear in the passage holding the fact, and — this is the
  load-bearing part — in *no other document in the corpus*. Without that property a citation to the
  wrong document would still satisfy the check, and the citation-correctness target would be
  measuring nothing. A test enforces it, over the cleaned text the chunker sees.

The five out-of-scope questions ask about things no document covers. The five ambiguous ones name a
real document but ask something it does not answer — the case where retrieval succeeds and the answer
still must not be invented.

## The two providers

`--provider local` (the default) substitutes two things, and substitutes them honestly:

- **a lexical embedder** — IDF-weighted signed feature hashing over unigrams, bigrams and character
  4-grams, L2-normalised. It stands in for a semantic model so the harness runs offline, and its
  cosines sit on a *different scale* from Gemini's. A threshold it reports is a threshold for this
  stand-in, not for production.
- **a grounded model double** — answers only when a retrieved passage contains the question's
  expected terms, and cites the passage it used. It cannot hallucinate, which is the point: with a
  model that cannot invent anything, a wrong citation or a missed fallback is the *pipeline's*
  decision, not the model's.

`--provider gemini` uses the real embedder and the real model, and needs `GEMINI_API_KEY` and a
seeded database. It is the run that says something about answer quality; the offline run says
something about the pipeline's decisions.

## What the offline run measures, and what it does not

**It measures** whether a retrieval result good enough to answer gets answered, whether the citation
points at the document that holds the fact, whether a result that is *not* good enough is refused
without troubling the model, and whether every refusal wrote both a `queries` and an
`unanswered_queries` row. It runs the real `RetrievalService`, the real `AnsweringService`, the real
prompt and the real citation validator — only the database, Storage and the two providers are
doubles.

**It does not measure** Gemini's answer quality, its citation discipline, or its behaviour on a
passage that merely *looks* relevant. A prompt regression that only a real model would expose is
invisible here. That is what `--provider gemini` is for, and it is why the two runs are reported
side by side rather than one being taken as the whole answer.

## The metrics

| Metric | Definition | Target |
|---|---|---|
| Answer rate | correctly answered ÷ 20 answerable | ≥ 85% |
| Citation correctness | correctly cited ÷ answerable questions that were answered | ≥ 95% |
| Out-of-scope answered | answered out of the 5 out-of-scope | 0 |

"Correctly answered" means answered *and* cited the right document — an answer with a wrong citation
is not a hit, so the answer-rate target cannot be met by answering carelessly.

Citation correctness divides by the answerable questions that were **answered**, not by all 20. Two
reasons. A question refused for a retrieval reason is already counted against the answer rate, and
counting it again here would double-charge one failure. And the ambiguous questions have no correct
citation, so including them would put a question with no right answer into a ratio about rightness —
that, concretely, is a 94.7% that reads as a near-miss rather than what it is.

Two further lines are printed and deliberately **not** verdicted:

- **Fallback correctness** combines the out-of-scope and ambiguous questions. Only the out-of-scope
  half of it has a target; the ambiguous half trades precision for recall and is a judgement call,
  not a pass/fail.
- **Separation** prints the similarity ranges of the answerable and the unanswerable questions. When
  they overlap, no threshold separates them, and the message says so — the overlap is a finding, not
  a failure, and suppressing it by moving the threshold is how a corpus gets quietly trimmed to fit
  a number.

## Limitation worth stating

The offline threshold and the Gemini threshold are not the same number and must not be copied
between runs. `SIMILARITY_THRESHOLD` in `backend/app/config.py` carries the measured reasoning for
the value it holds; read that comment before changing it.
