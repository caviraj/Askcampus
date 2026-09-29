"""The offline evaluation harness.

`AGENTS.md` section 9 requires an evaluation that "must run offline against a
seeded database and print metrics", with targets of an answer rate of at least
85 percent, citation correctness of at least 95 percent, and zero answers on
out-of-scope questions. This module is the "seeded database" and the scoring;
`run_eval.py` is the command.

What is real here and what is not, because a metric is only meaningful next to
the thing it measured:

**Real.** The corpus documents go through the same loader path as an upload: the
seeded text is parsed into `ExtractedDocument`, cleaned, and split by the real
heading-aware chunker in `app.services.chunking`. The real `RetrievalService`,
`AnsweringService`, citation validation, fallback decision and query logging all
run unchanged -- nothing in this file reimplements a business rule. The RRF merge
is a port of `hybrid_search` from migration 0002, kept in step with it by
`backend/tests/test_eval_harness.py`.

**Not real.** The embedding provider and the LLM are doubles, because there is no
live Supabase project and no API key in this environment. The embedding double is
a lexical one -- IDF-weighted hashed term vectors -- so cosine similarity in this
run reflects shared vocabulary rather than shared meaning. The consequence is
specific and worth stating plainly: **the answer rate and citation correctness
measured here describe the pipeline's decision-making, not Gemini's answer
quality, and the threshold this run selects is calibrated to a lexical proxy, not
to `gemini-embedding-001`'s similarity scale.** `run_eval.py --provider gemini`
runs the same corpus and the same questions against the real providers, and is
the run whose threshold is transferable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.services.answering import AnsweringService
from app.services.chunking import Chunk, chunk_document
from app.services.cleaning import clean_document
from app.services.embedding import EmbeddingService
from app.services.extraction import ExtractedDocument, ExtractedPage, TextBlock, render_labelled_row
from app.services.retrieval import RetrievalService, RetrievedChunk

EVAL_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Lexical analysis, shared by the two arms of the hybrid search
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")

# A short list in the spirit of Postgres's `english` stopword file rather than a
# copy of it. The two arms of the search both need the same tokenisation, and
# what matters for an evaluation is that it is applied consistently to the corpus,
# the questions and the keyword arm -- not that it matches a particular release of
# a particular stemmer.
_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both but by can cannot could did do does doing down
    during each few for from further had has have having he her here hers him his
    how i if in into is it its itself just me more most my no nor not of off on
    once only or other our out over own same she should so some such than that the
    their them then there these they this those through to too under until up very
    was we were what when where which while who whom why will with would you your
    """.split()
)

# Deliberately not Snowball. A light suffix trim is enough to make "fees" and
# "fee" the same term, which is what the keyword arm and the lexical embedder
# both need; a real stemmer would be a dependency for no measurable gain here.
_SUFFIXES = ("ing", "ies", "ied", "es", "ed", "s")


def stem(token: str) -> str:
    """A crude suffix trim, applied only when enough of the word survives.

    The plural rule is the one worth getting right, because getting it wrong is
    invisible. Stripping "es" from "programmes" gives "programm", while the
    singular "programme" has no suffix to strip and stays as it is -- so the two
    stop matching, and a question using one form silently fails to retrieve a
    passage using the other. "es" is therefore only dropped when the stem ends in
    a sibilant ("boxes", "branches"); everywhere else a lone "s" comes off.
    """
    for suffix in _SUFFIXES:
        if not token.endswith(suffix) or len(token) - len(suffix) < 3:
            continue
        base = token[: -len(suffix)]
        if suffix == "ies":
            return f"{base}y"
        if suffix == "es" and base.endswith(("s", "x", "z", "ch", "sh")):
            return base
        if suffix == "es":
            return token[:-1]
        return base
    return token


def lexemes(text: str) -> list[str]:
    """Stemmed, stopword-free terms, in the order they appear."""
    return [stem(token) for token in _WORD.findall(text.lower()) if token not in _STOPWORDS]


def _is_separator(cells: Sequence[str]) -> bool:
    """Whether a table row is the `|---|:--:|` rule rather than data."""
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def content_terms(text: str) -> set[str]:
    """The distinct terms a question is *about*, for the grounded model double.

    Short tokens are dropped on top of the stopword list: a lone "me" or "ok"
    carries no topic, and leaving them in lets the double claim an overlap where
    a real model would see none.
    """
    return {token for token in lexemes(text) if len(token) > 2}


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedDocument:
    """One corpus document, with the columns the upload form fills."""

    document_id: UUID
    title: str
    category: str
    department: str | None
    academic_year: str | None
    updated_at: str | None
    extracted: ExtractedDocument
    chunks: list[Chunk]


@dataclass(frozen=True)
class SeededChunk:
    """A chunk row, with its vector attached."""

    chunk_id: UUID
    document_id: UUID
    index: int
    content: str
    page_number: int | None
    section_heading: str | None
    embedding: list[float]


def load_corpus(corpus_dir: Path, settings: Settings) -> tuple[list[SeedDocument], list[Chunk]]:
    """Parse and chunk every document in the manifest.

    Returns the documents and the flat chunk list, because ingestion needs the
    former and embedding needs the latter.
    """
    manifest = _read_json(corpus_dir.parent / "corpus.json")
    cleaned = corpus_documents(corpus_dir)
    documents: list[SeedDocument] = []
    all_chunks: list[Chunk] = []

    for entry in manifest["documents"]:
        extracted = cleaned[entry["title"]]
        chunks = chunk_document(extracted, settings)
        documents.append(
            SeedDocument(
                document_id=uuid4(),
                title=entry["title"],
                category=entry["category"],
                department=entry.get("department"),
                academic_year=entry.get("academic_year"),
                updated_at=entry.get("updated_at"),
                extracted=extracted,
                chunks=chunks,
            )
        )
        all_chunks.extend(chunks)

    return documents, all_chunks


def corpus_documents(corpus_dir: Path) -> dict[str, ExtractedDocument]:
    """Every corpus document, parsed and cleaned, keyed by title.

    The first two of the three steps `load_corpus` takes, on their own, for a
    caller whose question is about the text rather than about retrieval.
    `backend/tests/test_eval_targets.py` is that caller: an `expected_terms`
    string only makes a citation check meaningful if it names a passage in one
    document and in no other, and the text to ask that of is this one -- after
    the wrapped lines are joined and the table rows are labelled -- not the raw
    file, where a term straddling a line break looks absent when it is present.
    """
    manifest = _read_json(corpus_dir.parent / "corpus.json")
    documents: dict[str, ExtractedDocument] = {}
    for entry in manifest["documents"]:
        parsed = parse_document(
            (corpus_dir / entry["file"]).read_text(encoding="utf-8"),
            page_marker=manifest["page_marker"],
        )
        documents[entry["title"]] = clean_document(parsed)
    return documents


def parse_document(text: str, *, page_marker: str) -> ExtractedDocument:
    """Turn an authored text file into the structure an extractor would produce.

    The three block kinds the chunker distinguishes are all reachable:
    `#`-prefixed lines are headings at their level, `|`-delimited runs are table
    rows rendered through the same `render_labelled_row` the PDF and DOCX
    extractors use, and everything else is a paragraph. Wrapped lines are joined,
    because the files are wrapped for reading and a hard break mid-sentence would
    otherwise become a chunk boundary.
    """
    marker = re.compile(page_marker)
    pages: list[ExtractedPage] = [ExtractedPage(page_number=1)]
    paragraph: list[str] = []
    table: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            pages[-1].blocks.append(TextBlock(text=" ".join(paragraph), kind="paragraph"))
            paragraph.clear()

    def flush_table() -> None:
        if not table:
            return
        # The first row is the header and every row after it is data rendered
        # under those labels. A markdown `|---|` separator is allowed and skipped
        # rather than required: requiring it would silently drop the first data
        # row of a table written without one, and the missing row would look like
        # a retrieval failure rather than a parsing one.
        labels = table[0]
        for row in table[1:]:
            if _is_separator(row):
                continue
            pages[-1].blocks.append(
                TextBlock(text=render_labelled_row(labels, row), kind="table_row")
            )
        table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        page = marker.match(stripped)
        if page:
            flush_paragraph()
            flush_table()
            pages.append(ExtractedPage(page_number=int(page.group(1))))
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            flush_table()
            level = len(stripped) - len(stripped.lstrip("#"))
            pages[-1].blocks.append(
                TextBlock(text=stripped[level:].strip(), kind="heading", heading_level=level)
            )
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            table.append([cell.strip() for cell in stripped.strip("|").split("|")])
            continue
        if not stripped:
            flush_paragraph()
            flush_table()
            continue
        paragraph.append(stripped)

    flush_paragraph()
    flush_table()
    return ExtractedDocument(pages=pages, page_count=len(pages))


# ---------------------------------------------------------------------------
# The two provider doubles
# ---------------------------------------------------------------------------


class LexicalEmbeddingProvider:
    """IDF-weighted hashed term vectors, with unit length.

    A stand-in for a real embedder, and an honest one: it makes cosine similarity
    mean *shared vocabulary*, so the retrieval arm behaves like a search engine
    and the run is reproducible with no network and no key. It is fit on the
    corpus first, which is what supplies the IDF weights -- without them every
    common word ("college", "student") would contribute as much as the one term
    the question turns on, and the separation between in-scope and out-of-scope
    questions would collapse.

    Signed feature hashing rather than a vocabulary dictionary: two different
    n-grams landing in one bucket cancel about as often as they reinforce, so a
    collision costs precision instead of silently conflating two terms.
    """

    def __init__(self, dimensions: int = 768) -> None:
        self._dimensions = dimensions
        self._idf: dict[str, float] = {}

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def fit(self, texts: Iterable[str]) -> None:
        """Learn IDF weights from the chunk texts.

        Squared, because the linear form barely separates anything at this corpus
        size: with 33 chunks, a term in three of them scores 2.1 against 1.5 for a
        term in twenty, and the one term the question turns on carries hardly more
        than the filler around it. Squaring turns that 2.1 against 1.5 into 4.4
        against 2.2, which is the ratio a retrieval score needs to be useful.

        Worth being plain about the direction this pushes: it makes a rare shared
        term matter more, which is what a real embedding model does through its
        training rather than through a formula.
        """
        documents = [set(_features(text)) for text in texts]
        total = len(documents)
        counts: Counter[str] = Counter()
        for features in documents:
            counts.update(features)
        self._idf = {
            feature: (math.log((total + 1) / (count + 1)) + 1.0) ** 2
            for feature, count in counts.items()
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        counts = Counter(_features(text))
        if not counts:
            # A question of nothing but stopwords still has to return a vector of
            # the right width; every real similarity against it is ~0, which is
            # the correct outcome for a question that says nothing.
            return [0.0] * self._dimensions

        vector = [0.0] * self._dimensions
        for feature, count in counts.items():
            # Sublinear term frequency: the tenth mention of a word says much
            # less about the passage than the first.
            weight = (1.0 + math.log(count)) * self._idf.get(feature, 1.0)
            signed = _signed_bucket(feature, self._dimensions)
            vector[signed.index] += signed.sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


@dataclass(frozen=True)
class _Bucket:
    index: int
    sign: float


def _signed_bucket(feature: str, dimensions: int) -> _Bucket:
    """A stable index and sign for a feature, from its digest.

    `hash()` is salted per process, so it would give a different corpus every run
    and make the whole evaluation irreproducible.
    """
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    raw = int.from_bytes(digest, "big")
    return _Bucket(index=raw % dimensions, sign=1.0 if (raw >> 63) & 1 else -1.0)


# Subword shingles, the stand-in for what a real embedding model gets from its
# tokenizer: "submit" and "submission" share no word but share most of their
# character n-grams, and a word-only vocabulary would treat them as unrelated.
_SHINGLE = 4
_SHINGLE_PREFIX = "~"


def _features(text: str) -> list[str]:
    """Unigrams, word bigrams, and character shingles, in one flat list.

    Three views of the same text, because each catches what the others miss.
    Unigrams carry the topic, bigrams carry the phrase -- "late fee" is a
    different thing from "late" and "fee" happening to appear in one document --
    and shingles carry the morphology. They are all just features to be hashed
    and IDF-weighted, so combining them is one list rather than a fusion step.
    """
    tokens = lexemes(text)
    features = list(tokens)
    features.extend(f"{first} {second}" for first, second in zip(tokens, tokens[1:], strict=False))
    for token in tokens:
        padded = f"{_SHINGLE_PREFIX}{token}{_SHINGLE_PREFIX}"
        features.extend(
            padded[start : start + _SHINGLE] for start in range(max(len(padded) - _SHINGLE + 1, 0))
        )
    return features


@dataclass(frozen=True)
class PromptedSource:
    """One `<<<SOURCE S1>>>` block, as the model double reads it back."""

    label: str
    section: str | None
    content: str


_SOURCE_BLOCK = re.compile(
    r"<<<SOURCE (?P<label>S\d+)>>>\n(?P<body>.*?)\n<<<END SOURCE (?P=label)>>>",
    re.DOTALL,
)
_QUESTION_LINE = re.compile(r"^Question: (.*)$", re.MULTILINE)
_SECTION_LINE = re.compile(r"^Section: (.*)$", re.MULTILINE)
_CONTENT_MARKER = "Content:\n"
_REJECTED = "Your previous response was rejected"


class GroundedLLMProvider:
    """A model double that follows the prompt's rules, by reading the prompt.

    It answers with a sentence copied out of the source it used and cites that
    source's label -- never a title, a page or a date, because the prompt never
    asks for one. This is what makes the run informative in two directions: a
    citation-correctness failure here means the *pipeline* attached the wrong
    chunk to a label rather than that a model hallucinated a document name, and
    the answer text can be checked against the corpus by eye.

    The one judgement it makes is the one `ARCHITECTURE.md` section 6 rule 2 asks
    of a real model: if no supplied source overlaps the question, it reports
    `answerable: false` rather than answering from a passage that merely happened
    to be retrieved.
    """

    # Two shared content terms, at both the source and the sentence level. One
    # would let any passage mentioning "college" answer any question about it.
    MIN_OVERLAP = 2

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.retries: int = 0

    async def generate_json(self, prompt: str, schema: type[Any]) -> Any:
        self.prompts.append(prompt)
        if _REJECTED in prompt:
            self.retries += 1

        question = _QUESTION_LINE.search(prompt)
        terms = content_terms(question.group(1)) if question else set()

        best_source: PromptedSource | None = None
        best_sentence, best_overlap = "", 0
        # Strict `>` keeps the earliest source on a tie, which is the one the
        # search ranked highest -- a model reading the prompt top to bottom would
        # stop at the first source that answers the question, not the last.
        for source in _parse_sources(prompt):
            sentence, overlap = _best_sentence(source.content, terms)
            if overlap > best_overlap:
                best_source, best_sentence, best_overlap = source, sentence, overlap

        if best_source is None or best_overlap < self.MIN_OVERLAP:
            return schema(answerable=False, answer="", used_sources=[])
        return schema(answerable=True, answer=best_sentence, used_sources=[best_source.label])


def _parse_sources(prompt: str) -> list[PromptedSource]:
    sources: list[PromptedSource] = []
    for match in _SOURCE_BLOCK.finditer(prompt):
        body = match.group("body")
        section = _SECTION_LINE.search(body)
        _, _, content = body.partition(_CONTENT_MARKER)
        sources.append(
            PromptedSource(
                label=match.group("label"),
                section=section.group(1) if section else None,
                content=content.strip(),
            )
        )
    return sources


def _best_sentence(content: str, terms: set[str]) -> tuple[str, int]:
    """The sentence of `content` that shares the most terms with the question.

    Table rows are one sentence each already, and are what a large part of this
    corpus is made of, so the split has to keep "Label: value; Label: value"
    together. Splitting on a full stop inside a decimal number would break a fee
    in half, hence the lookahead.
    """
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", content)
    best_sentence, best_overlap = "", 0
    for sentence in sentences:
        overlap = len(content_terms(sentence) & terms)
        if overlap > best_overlap:
            best_sentence, best_overlap = sentence.strip(), overlap
    return best_sentence, best_overlap


# ---------------------------------------------------------------------------
# The retrieval seam
# ---------------------------------------------------------------------------


class LocalChunkRepository:
    """`ChunkRepository` over the seeded corpus, ranking the way the database does.

    This is a port of `hybrid_search` in `supabase/migrations/0002_hybrid_search.sql`
    and is meant to stay one: the same two 20-candidate arms, the same Reciprocal
    Rank Fusion constant of 60, the same `similarity` column carrying the raw
    cosine and nothing else, and the same category filter applied to the
    *document's* category rather than the chunk's.

    Two honest gaps. Postgres's `ts_rank` is approximated by summed term
    frequency, and `websearch_to_tsquery('english', ...)` is approximated by
    "every stemmed question term appears". Both affect only the *ordering* of the
    keyword arm, which feeds RRF; neither affects `similarity`, which is the
    column the fallback threshold is compared against. So a divergence here moves
    which passages are retrieved, never the number the threshold decides on.

    The two arms are both computed from the corpus in memory rather than from a
    ranking handed in, which is the opposite of the test double in
    `backend/tests/fakes.py`. That is the point: an evaluation with a scripted
    ranking would measure the script.
    """

    # Matching migration 0002's `limit 20` on each arm.
    CANDIDATES = 20
    # And its `1.0 / (60 + rank)`.
    RRF_K = 60

    def __init__(self, documents: Sequence[SeedDocument], chunks: Sequence[SeededChunk]) -> None:
        self.documents = {document.document_id: document for document in documents}
        self.chunks = list(chunks)
        self.searches: list[str | None] = []

    async def search(
        self, *, query_text: str, embedding: list[float], match_count: int, category: str | None
    ) -> list[dict[str, Any]]:
        self.searches.append(category)
        eligible = [chunk for chunk in self.chunks if self._in_scope(chunk, category)]

        semantic = sorted(
            ((_cosine(embedding, chunk.embedding), chunk) for chunk in eligible),
            key=lambda pair: pair[0],
            reverse=True,
        )[: self.CANDIDATES]
        semantic_rank = {chunk.chunk_id: rank for rank, (_, chunk) in enumerate(semantic, start=1)}
        similarity = {chunk.chunk_id: score for score, chunk in semantic}

        keyword = self._keyword_arm(query_text, eligible)
        keyword_rank = {chunk.chunk_id: rank for rank, chunk in enumerate(keyword, start=1)}

        hits: list[dict[str, Any]] = []
        for chunk in eligible:
            ranks = [
                rank
                for rank in (semantic_rank.get(chunk.chunk_id), keyword_rank.get(chunk.chunk_id))
                if rank is not None
            ]
            if not ranks:
                continue
            hits.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "score": sum(1.0 / (self.RRF_K + rank) for rank in ranks),
                    # NULL for a keyword-only hit, exactly as the SQL returns it.
                    "similarity": similarity.get(chunk.chunk_id),
                }
            )

        # Ties broken by chunk id so the ordering is total and the run is
        # reproducible; the SQL leaves this to the planner, which is fine there
        # because nothing downstream depends on the order of equal scores.
        hits.sort(key=lambda hit: (-hit["score"], str(hit["chunk_id"])))
        return hits[:match_count]

    async def hydrate(self, hits: list[dict[str, Any]]) -> list[RetrievedChunk]:
        by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        hydrated: list[RetrievedChunk] = []
        for hit in hits:
            chunk = by_id.get(_as_uuid(hit["chunk_id"]))
            if chunk is None:
                continue
            document = self.documents[chunk.document_id]
            hydrated.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    score=float(hit["score"]),
                    similarity=hit["similarity"],
                    content=chunk.content,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    document_title=document.title,
                    department=document.department,
                    document_updated_at=document.updated_at,
                )
            )
        return hydrated

    def _in_scope(self, chunk: SeededChunk, category: str | None) -> bool:
        if category is None:
            return True
        return self.documents[chunk.document_id].category == category

    def _keyword_arm(self, query_text: str, eligible: Sequence[SeededChunk]) -> list[SeededChunk]:
        """Chunks containing every question term, ranked by how often they recur."""
        wanted = set(lexemes(query_text))
        if not wanted:
            return []
        scored = []
        for chunk in eligible:
            present = Counter(lexemes(chunk.content))
            if not wanted <= set(present):
                continue
            scored.append((sum(present[term] for term in wanted), chunk))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].chunk_id)))
        return [chunk for _, chunk in scored[: self.CANDIDATES]]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Both operands are unit length, so the dot product is the cosine."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


# ---------------------------------------------------------------------------
# The query log
# ---------------------------------------------------------------------------


@dataclass
class RecordedQuery:
    """One `log_query` call, reduced to what the evaluation checks."""

    question: str
    answered: bool
    unanswered: bool
    top_score: float | None
    document_titles: list[str]


class RecordingQueryLog:
    """`QueryLogRepository` that keeps the flags rather than the rows.

    `AGENTS.md` section 6.6 requires a fallback to write both a `queries` row and
    an `unanswered_queries` row. The real repository does that in one transaction
    keyed on the `unanswered` flag, so what a double can check is that the flag
    was set on exactly the fallbacks -- which is what this records.
    """

    def __init__(self) -> None:
        self.entries: list[RecordedQuery] = []

    async def log_query(self, **kwargs: Any) -> None:
        self.entries.append(
            RecordedQuery(
                question=kwargs["question"],
                answered=kwargs["answered"],
                unanswered=kwargs["unanswered"],
                top_score=kwargs["top_score"],
                document_titles=[
                    source.document_title
                    for source in kwargs["sources"]
                    if source.document_title is not None
                ],
            )
        )

    async def record_feedback(self, *, query_id: UUID, session_id: UUID, helpful: bool) -> bool:
        return True


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    """One row of `eval/questions.json`."""

    id: str
    kind: str
    question: str
    expected_document: str | None = None
    expected_section: str | None = None
    expected_terms: tuple[str, ...] = ()
    related_document: str | None = None

    @property
    def expects_fallback(self) -> bool:
        return self.kind in {"out_of_scope", "ambiguous"}


@dataclass
class Judgement:
    """What one question produced, and how it scored."""

    question: Question
    answered: bool
    answer: str
    document_titles: list[str]
    sections: list[str | None]
    snippets: list[str]
    best_similarity: float | None
    retrieved_titles: list[str] = field(default_factory=list)

    @property
    def answer_rate_hit(self) -> bool:
        """Answered, from the expected document, with the expected passage cited."""
        if not self.answered:
            return False
        return any(self._supports(index) for index in range(len(self.snippets)))

    @property
    def citation_correct(self) -> bool:
        """Every citation supports the answer.

        Every one, not at least one: a source slip that names a document the
        answer did not come from is a fabricated citation, and the student has no
        way to tell which of the two slips to trust.
        """
        if not self.answered:
            return False
        return all(self._supports(index) for index in range(len(self.snippets)))

    def _supports(self, index: int) -> bool:
        question = self.question
        if question.expected_document is None:
            return False
        if self.document_titles[index] != question.expected_document:
            return False
        if question.expected_terms and not any(
            term.lower() in self.snippets[index].lower() for term in question.expected_terms
        ):
            return False
        section = self.sections[index]
        if question.expected_section is not None and (
            section is None or question.expected_section not in section
        ):
            return False
        return True


@dataclass(frozen=True)
class Metrics:
    """The three numbers `AGENTS.md` section 9 names, plus what explains them."""

    threshold: float
    # The 20 answerable questions, counted three ways: how many there are, how
    # many got an answer whose citation points at the passage that holds the
    # fact, and -- the narrower pair -- how many were answered at all and how
    # many of those cited correctly throughout.
    answerable_total: int
    answer_hits: int
    answerable_answered: int
    answerable_correct: int
    out_of_scope_total: int
    out_of_scope_answered: int
    ambiguous_total: int
    ambiguous_answered: int
    log_rows: int
    # Rows written with `unanswered = true`, which is the flag the real repository
    # turns into the second row. AGENTS.md section 6.6 wants one of these per
    # fallback and none anywhere else, so the two counts have to agree.
    unanswered_rows: int
    fallbacks: int
    # Fallbacks caused by a provider that could not be reached rather than by the
    # documents. Zero offline, where the doubles never fail; the gemini run
    # reports what it saw, because those questions were never put to the model and
    # counting them against the pipeline would blame the code for an outage.
    provider_errors: int = 0

    @property
    def answer_rate(self) -> float:
        return _ratio(self.answer_hits, self.answerable_total)

    @property
    def citation_correctness(self) -> float:
        """Of the answerable questions that were answered, how many cited correctly.

        The denominator is the answers given to questions that *have* a right
        answer, not every answer given. A question the corpus does not answer has
        no citation to be correct -- calling one wrong there would fold the
        precision measure into this one and leave the two targets in section 9
        measuring the same thing. Those answers are reported on their own, as
        outstanding out-of-scope or ambiguous counts.
        """
        return _ratio(self.answerable_correct, max(self.answerable_answered, 1))

    @property
    def fallback_total(self) -> int:
        """Every question the corpus does not answer, of either kind."""
        return self.out_of_scope_total + self.ambiguous_total

    @property
    def fallback_correctness(self) -> float:
        """How often the system said so instead of answering.

        Over the out-of-scope *and* ambiguous questions together, because both
        name something the corpus does not answer and the honest response to
        either is the same. The out-of-scope count is also reported on its own:
        `AGENTS.md` section 9 makes zero answers there a hard target, while an
        ambiguous question answered from the passage it half-matches is a
        precision failure rather than a fabrication.
        """
        missed = self.out_of_scope_answered + self.ambiguous_answered
        return _ratio(self.fallback_total - missed, self.fallback_total)

    def meets_targets(self) -> bool:
        return (
            self.answer_rate >= ANSWER_RATE_TARGET
            and self.citation_correctness >= CITATION_TARGET
            and self.out_of_scope_answered == 0
        )


ANSWER_RATE_TARGET = 0.85
CITATION_TARGET = 0.95


def _ratio(part: int, whole: int) -> float:
    return part / whole if whole else 1.0


async def run_questions(
    *,
    answerer: AnsweringService,
    retrieval: RetrievalService,
    questions: Sequence[Question],
    query_log: RecordingQueryLog,
    session_id: UUID | None = None,
) -> list[Judgement]:
    """Ask every question through the real pipeline and score what came back."""
    session = session_id or uuid4()
    judgements: list[Judgement] = []

    for question in questions:
        outcome = await answerer.answer(session_id=session, question=question.question)
        # Retrieval is run a second time, unfiltered and unfollowed by anything,
        # purely to report the number the threshold was compared against. Without
        # it a false fallback says "the documents did not answer this" and gives
        # no way to tell a threshold set too high from a chunker that lost the
        # passage.
        probe = await retrieval.retrieve(search_text=question.question, category=None)
        judgements.append(
            Judgement(
                question=question,
                answered=outcome.answered,
                answer=outcome.answer,
                document_titles=[citation.document_title for citation in outcome.citations],
                sections=[citation.section for citation in outcome.citations],
                snippets=[citation.snippet for citation in outcome.citations],
                best_similarity=probe.best_similarity,
                retrieved_titles=_unique(chunk.document_title for chunk in probe.chunks),
            )
        )

    return judgements


def summarise(
    judgements: Sequence[Judgement],
    *,
    threshold: float,
    log_rows: int,
    unanswered_rows: int,
    provider_errors: int = 0,
) -> Metrics:
    answerable = [item for item in judgements if item.question.kind == "answerable"]
    out_of_scope = [item for item in judgements if item.question.kind == "out_of_scope"]
    ambiguous = [item for item in judgements if item.question.kind == "ambiguous"]

    return Metrics(
        threshold=threshold,
        answerable_total=len(answerable),
        answer_hits=sum(1 for item in answerable if item.answer_rate_hit),
        answerable_answered=sum(1 for item in answerable if item.answered),
        answerable_correct=sum(1 for item in answerable if item.answered and item.citation_correct),
        out_of_scope_total=len(out_of_scope),
        out_of_scope_answered=sum(1 for item in out_of_scope if item.answered),
        ambiguous_total=len(ambiguous),
        ambiguous_answered=sum(1 for item in ambiguous if item.answered),
        log_rows=log_rows,
        unanswered_rows=unanswered_rows,
        fallbacks=sum(1 for item in judgements if not item.answered),
        provider_errors=provider_errors,
    )


def _unique(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def read_questions(path: Path) -> list[Question]:
    payload = _read_json(path)
    return [
        Question(
            id=row["id"],
            kind=row["kind"],
            question=row["question"],
            expected_document=row.get("expected_document"),
            expected_section=row.get("expected_section"),
            expected_terms=tuple(row.get("expected_terms", ())),
            related_document=row.get("related_document"),
        )
        for row in payload["questions"]
    ]


async def seed(
    *, settings: Settings, corpus_dir: Path, provider: Any
) -> tuple[list[SeedDocument], LocalChunkRepository]:
    """Build the searchable corpus: chunk, embed, and index it.

    Embedding goes through the real `EmbeddingService`, so the batching and the
    content-addressed cache are exercised rather than bypassed.
    """
    documents, chunks = load_corpus(corpus_dir, settings)

    if isinstance(provider, LexicalEmbeddingProvider):
        provider.fit(chunk.content for chunk in chunks)

    embeddings = EmbeddingService(provider, settings, _NoCache())
    vectors = await embeddings.embed_texts([chunk.content for chunk in chunks])

    seeded: list[SeededChunk] = []
    offset = 0
    for document in documents:
        for chunk in document.chunks:
            seeded.append(
                SeededChunk(
                    chunk_id=uuid4(),
                    document_id=document.document_id,
                    index=chunk.index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    embedding=vectors[offset],
                )
            )
            offset += 1

    return documents, LocalChunkRepository(documents, seeded)


class _NoCache:
    """An `EmbeddingCache` that stores nothing.

    The evaluation seeds once per run, so a cache would only be a place for a
    stale vector from an earlier corpus to survive into this one.
    """

    async def get_many(
        self, content_hashes: list[str], *, model: str, dimensions: int
    ) -> dict[str, list[float]]:
        return {}

    async def put_many(
        self, entries: dict[str, list[float]], *, model: str, dimensions: int
    ) -> None:
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
