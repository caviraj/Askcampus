"""The Phase 6 evaluation: seed corpus, question set, harness and runner.

A package rather than two loose scripts so that `backend/tests/test_eval_targets.py`
can import the harness and assert the `AGENTS.md` section 9 targets, which is what
stops them regressing the next time a prompt, a chunk size or a threshold moves.
"""
