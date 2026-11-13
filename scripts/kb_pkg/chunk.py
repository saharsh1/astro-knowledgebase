# scripts/kb_pkg/chunk.py (from the owner's research vault, 2026-11-12)
"""Split extracted text into embed-sized chunks with source metadata.

The encoder reads at most 512 tokens (bge-large-en-v1.5; 510 after [CLS] and [SEP])
and silently drops the rest. With a token counter (``count``: list of words -> list of
token counts, from ``Embedder.token_counter()``) the windows are sized in tokens, so
every chunk fits. Without one (tests, fallback) they are sized in words.

Measured on 2026-11-10: the old 450-word paper windows had a median of 680 tokens;
98 % were cut. Scientific text runs at about 1.5 tokens per word, notes at about 2.
"""
import re
from typing import Callable, Optional

from .extract import first_author, paper_title
from .model import Chunk

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

MAX_TOKENS = 480        # under the encoder's 510, with a margin
OVERLAP_TOKENS = 64
WORDS, OVERLAP_WORDS = 300, 50   # fallback when no token counter is given

Counter = Optional[Callable[[list[str]], list[int]]]


def _windows(counts: list[int], limit: int, overlap: int):
    """(start, end) index windows over items whose summed counts stay <= limit.

    A single item above the limit gets a window of its own. Each next window starts
    so that the shared tail holds at most ``overlap``; every window advances.
    """
    n = len(counts)
    start = 0
    while start < n:
        end, total = start, 0
        while end < n and (end == start or total + counts[end] <= limit):
            total += counts[end]
            end += 1
        yield start, end
        if end >= n:
            break
        back, shared = end, 0
        while back > start + 1 and shared + counts[back - 1] <= overlap:
            back -= 1
            shared += counts[back]
        start = back


def _plan(words: list[str], count: Counter, budget: int | None = None):
    """Token counts and the (limit, overlap) to window ``words`` with."""
    if count is None:
        return [1] * len(words), (budget or WORDS), OVERLAP_WORDS
    return count(words), (budget or MAX_TOKENS), OVERLAP_TOKENS


PAPER_CHUNKS = "2"      # 2 (2026-11-13): each passage starts with the paper's title and section
_SECTION = re.compile(r"^(\d{1,2})((?:\.\d{1,2}){0,2})\.\s+([A-Z][^\n]{2,90})$")
_APPENDIX = re.compile(r"^Appendix\s+([A-Z])\s*:\s*([A-Z][^\n]{2,90})$")


def paper_sections(pages) -> list[tuple[str, int, str]]:
    """(word, page, section) for every word of a paper. A section heading is a line
    "3. Title" or "3.2. Title" (number, period, capital; at most 12 words; no closing
    comma, semicolon or period) whose number continues the count: the next section, or a
    subsection of the current one. Footnotes (no period after the number) and numbered list
    items (a full line whose next line goes on in lower case) do not pass. The
    section of a subsection is "3. Title / 3.2. Title". Also "Appendix A: Title"."""
    out, top_n, top, sub = [], 0, "", ""
    for page_no, text in pages:
        lines = [l.strip() for l in text.splitlines()]
        for i, s in enumerate(lines):
            m = _SECTION.match(s)
            nxt = next((l for l in lines[i + 1:] if l), "")
            runs_on = len(s) >= 45 and nxt[:1].islower()     # a full line that continues: a list item
            if m and len(s.split()) <= 12 and not s.endswith((",", ";", ".", ":")) and not runs_on:
                n = int(m.group(1))
                if not m.group(2) and top_n < n <= top_n + 2 and n < 30:   # +2: one missed heading does not stop the count
                    top_n, top, sub = n, s, ""
                elif m.group(2) and n == top_n:
                    sub = s
                elif m.group(2) and n == top_n + 1:               # "4.1." seen, "4." itself was missed
                    top_n, top, sub = n, f"{n}.", s
            else:
                m = _APPENDIX.match(s)
                if m and len(s.split()) <= 14:
                    top_n, top, sub = 99, s, ""          # no numbered section follows an appendix
            section = f"{top} / {sub}" if sub else top
            out += [(w, page_no, section) for w in s.split()]
    return out


def chunk_paper(source_id, pages, *, words=None, overlap=None, count: Counter = None):
    """Windows over the concatenated pages, tracking page spans and sections. Each passage
    starts with a line "<paper title> — <section>", so a passage from the middle of a
    paper still says which paper and which part it is from (the window is shortened by the
    length of that line).

    ``words``/``overlap`` force word windows (as before 2026-11-10); otherwise the
    windows are sized in tokens when ``count`` is given, in words when not.
    """
    tagged = paper_sections(pages)
    if not tagged:
        return []

    title = paper_title(source_id)
    author = first_author(source_id)
    plain = [w for w, _, _ in tagged]
    if words is not None:
        counts, limit, ov = [1] * len(plain), words, (overlap if overlap is not None else 0)
    else:
        counts, limit, ov = _plan(plain, count)
        longest = max({f"{title} — {s}" for _, _, s in tagged}, key=len).split()
        limit = max(limit // 2, limit - (sum(count(longest)) if count else len(longest)))
    chunks: list[Chunk] = []
    for ordinal, (a, b) in enumerate(_windows(counts, limit, ov)):
        window = tagged[a:b]
        section = window[len(window) // 3][2]          # the section most of the window is in
        head = f"{title} — {section}" if section else (title or "")
        chunks.append(Chunk(
            chunk_id=f"{source_id}#{ordinal}",
            source_id=source_id,
            source_type="paper",
            text=(head + "\n" if head else "") + " ".join(w for w, _, _ in window),
            title=title,
            author=author,
            page_start=window[0][1],
            page_end=window[-1][1],
            section=section or None,
            note_path=None,
        ))
    return chunks


def chunk_note(source_id, note_path, text, *, count: Counter = None):
    """One chunk per markdown heading section; whole file if no headings.

    A section too long for the encoder is split into overlapping windows; each window
    repeats the heading line and keeps the section name.
    """
    lines = text.splitlines()
    title = None
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    buf: list[str] = []

    def flush():
        has_body = any(line.strip() for line in buf)
        if current_heading is not None or has_body:
            sections.append((current_heading, buf.copy()))
        buf.clear()

    for line in lines:
        m = _HEADING.match(line)
        if m:
            flush()
            current_heading = m.group(2).strip()
            if title is None:
                title = current_heading
        else:
            buf.append(line)
    flush()

    if not sections:
        sections = [(None, lines)]

    texts: list[tuple[str | None, str]] = []
    for heading, body in sections:
        body_text = "\n".join(body).strip()
        header_line = f"{heading}\n" if heading else ""
        full = (header_line + body_text).strip()
        head_words = heading.split() if heading else []
        body_words = body_text.split()
        counts_all, limit, ov = _plan(head_words + body_words, count)
        if sum(counts_all) <= limit:
            texts.append((heading, full))
            continue
        head_cost = sum(counts_all[:len(head_words)])
        body_counts = counts_all[len(head_words):]
        for a, b in _windows(body_counts, max(1, limit - head_cost), ov):
            piece = " ".join(body_words[a:b])
            texts.append((heading, (header_line + piece).strip()))

    return [Chunk(
        chunk_id=f"{source_id}#{ordinal}",
        source_id=source_id,
        source_type="note",
        text=t,
        title=title,
        author=None,
        page_start=None,
        page_end=None,
        section=heading,
        note_path=note_path,
    ) for ordinal, (heading, t) in enumerate(texts)]
