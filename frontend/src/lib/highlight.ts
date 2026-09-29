/**
 * Which sentence in a passage supports the answer.
 *
 * DESIGN_SYSTEM.md section 7 asks for "the exact supporting sentence" marked in
 * `--highlight`. The API does not say which sentence that is: it returns the
 * whole chunk and the answer, and nothing that identifies one sentence of the
 * chunk as the evidence. So this picks it from the text itself.
 *
 * The rule is deterministic and conservative. A sentence scores by how many
 * distinct content words it shares with the answer, numbers counting double,
 * and the highest score wins. If nothing scores -- or the passage cannot be
 * split -- the result is `null` and the passage renders unmarked.
 *
 * Marking the wrong sentence would be a false claim about which part of a
 * document supports an answer, which is the one thing this product must not do.
 * Showing no mark looks incomplete; showing a wrong one destroys the citation.
 */

/** The snippet split into three adjacent pieces, so they can be rendered as
 *  three plain text nodes without ever parsing the passage as HTML. */
export interface HighlightSpan {
  before: string;
  match: string;
  after: string;
}

interface Segment {
  /** Index into the original string. */
  start: number;
  /** Exclusive, and excludes trailing whitespace so the mark is tight. */
  end: number;
}

// A sentence break: a terminator, whitespace, and something that starts a
// sentence. Two separate things keep abbreviations whole, and they are easy to
// confuse:
//
//  - The required `\s+`. "12.12.2026" and "Ph.D. 2019" never split, because the
//    period inside them is followed by a letter rather than a space.
//  - The lookahead, which is what keeps "Rs. 500" and "Nov. 2026" whole. It
//    deliberately does *not* list digits: "Rs. 500" is followed by a space and
//    then a digit, so admitting digits here would split it after the
//    abbreviation and offer "The fine is Rs." as a sentence that could be
//    marked. The cost is that a sentence genuinely beginning with a number is
//    not treated as a break -- rare, and the failure is a longer mark rather
//    than a wrong one, which is the direction this module errs in throughout.
//
// Kept as a global regex and driven with `exec`, which is stateful: `lastIndex`
// is reset before every use below. A `split` on this pattern would not work,
// because split discards the separator and the offsets would then be wrong by
// however much whitespace sat between two sentences.
const SENTENCE_BREAK = /(?<=[.!?])\s+(?=[A-Z"'“(])/g;

const WORD = /[\p{L}\p{N}]+/gu;
const WHITESPACE = /\s/;

// A short stopword list rather than a full one. It exists to stop "the" and
// "is" from making every sentence look like a match; a longer list buys little
// and risks dropping a word that actually carries meaning here.
const STOPWORDS = new Set([
  "a", "about", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
  "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in",
  "into", "is", "it", "its", "me", "must", "my", "no", "not", "of", "on", "or",
  "should", "so", "than", "that", "the", "their", "them", "then", "there",
  "these", "they", "this", "to", "up", "was", "we", "were", "what", "when",
  "where", "which", "who", "will", "with", "would", "you", "your",
]);

function tokenize(text: string): string[] {
  const matches = text.toLowerCase().match(WORD);
  if (!matches) return [];
  return matches.filter((token) => token.length > 1 && !STOPWORDS.has(token));
}

/**
 * Sentence spans covering the whole string, in order.
 *
 * Newlines split first: a chunk carries headings and rendered table rows on
 * lines of their own, and a heading glued to the sentence after it would score
 * as one unit and could then be marked whole.
 */
function segment(snippet: string): Segment[] {
  const segments: Segment[] = [];
  let offset = 0;

  for (const line of snippet.split("\n")) {
    const boundaries: number[] = [0];
    SENTENCE_BREAK.lastIndex = 0;
    for (let match = SENTENCE_BREAK.exec(line); match; match = SENTENCE_BREAK.exec(line)) {
      // Past the whitespace the break consumed, which is where the next
      // sentence actually begins.
      boundaries.push(match.index + match[0].length);
    }
    boundaries.push(line.length);

    for (let index = 0; index < boundaries.length - 1; index += 1) {
      const start = offset + (boundaries[index] ?? 0);
      let end = offset + (boundaries[index + 1] ?? line.length);
      while (end > start && WHITESPACE.test(snippet[end - 1] ?? "")) end -= 1;
      if (end > start) segments.push({ start, end });
    }
    // Plus the newline that `split` removed.
    offset += line.length + 1;
  }

  return segments;
}

export function selectSupportingSentence(snippet: string, answer: string): HighlightSpan | null {
  const answerTokens = new Set(tokenize(answer));
  if (answerTokens.size === 0) return null;

  const segments = segment(snippet);
  let best: Segment | null = null;
  let bestScore = 0;

  for (const candidate of segments) {
    const seen = new Set<string>();
    let score = 0;
    for (const token of tokenize(snippet.slice(candidate.start, candidate.end))) {
      if (seen.has(token) || !answerTokens.has(token)) continue;
      seen.add(token);
      // A shared number is the strongest available evidence: prompt rule 3
      // makes the model copy dates and figures exactly rather than paraphrase
      // them, so an exact match is near-conclusive where a shared noun is not.
      score += /\d/.test(token) ? 2 : 1;
    }
    // Strictly greater, so a tie keeps the earlier segment: deterministic
    // without a tiebreak key, and the earlier sentence is the likelier subject.
    if (score > bestScore) {
      bestScore = score;
      best = candidate;
    }
  }

  if (best === null || bestScore === 0) return null;

  // Three slices of the same string, so `before + match + after === snippet`.
  // The component renders them as text nodes and never as HTML, so a dropped
  // character would silently change the passage rather than throw.
  return {
    before: snippet.slice(0, best.start),
    match: snippet.slice(best.start, best.end),
    after: snippet.slice(best.end),
  };
}
