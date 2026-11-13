"""Convert LaTeXML-generated HTML (the Gaia documentation) to Obsidian Markdown.

- paragraphs, lists, block quotes, headings;
- tables -> Markdown pipe tables (the documentation's flag-bit tables survive intact);
- math -> $alttext$ / $$alttext$$ (the LaTeX source LaTeXML keeps in `alttext`);
- typewriter text -> `code`;
- links: a `resolve(href)` callback may turn a link into a wikilink; others keep their text;
- figures: the caption only ("Figure 7.3: ..."); images are not copied.
"""
from __future__ import annotations

import copy
import re
from typing import Callable

from bs4 import BeautifulSoup, NavigableString, Tag

Resolver = Callable[[str], "str | None"]       # href -> "Note stem#anchor" or None

SKIP = {"script", "style", "header", "footer", "nav", "button", "svg", "img", "annotation", "annotation-xml"}
BLOCK = {"p", "div", "section", "ul", "ol", "li", "table", "blockquote", "figure", "h1", "h2", "h3",
         "h4", "h5", "h6", "dl", "dt", "dd", "pre", "article"}


def classes(t: Tag) -> set[str]:
    return set(t.get("class") or [])


def soup(html: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _space(s: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", s)


def inline(node, resolve: Resolver | None = None) -> str:
    """Text of an element with inline Markdown."""
    if isinstance(node, NavigableString):
        return _space(str(node))
    if not isinstance(node, Tag) or node.name in SKIP:
        return ""
    c = classes(node)
    if node.name == "math":
        alt = (node.get("alttext") or node.get_text(" ")).strip()
        return f"$${alt}$$" if node.get("display") == "block" else f"${alt}$"
    if node.name == "br":
        return " "
    inner = "".join(inline(ch, resolve) for ch in node.children)
    if "ltx_note" in c:                                       # footnote: keep its text in brackets
        body = node.find(class_="ltx_note_content")
        text = inline(body, resolve) if body else inner
        text = re.sub(r"^\s*\d+\s*", "", text)
        return f" (note: {text.strip()})"
    if node.name == "a":
        href = node.get("href") or ""
        target = resolve(href) if (resolve and href) else None
        text = inner.strip()
        if target:
            return f"[[{target}|{text}]]" if text else f"[[{target}]]"
        if href.startswith("http") and text and text != href:
            return f"[{text}]({href})"
        return inner
    if "ltx_font_typewriter" in c and inner.strip() and "`" not in inner and "[[" not in inner:
        return f"`{inner.strip()}`"
    if node.name in ("b", "strong") or "ltx_font_bold" in c:
        return f"**{inner.strip()}**" if inner.strip() else inner
    if node.name in ("i", "em") or "ltx_font_italic" in c:
        return f"*{inner.strip()}*" if inner.strip() else inner
    if node.name == "sup":
        return f"^{inner.strip()}"
    if node.name == "sub":
        return f"_{inner.strip()}"
    return inner


def table_md(t: Tag, resolve: Resolver | None) -> str:
    rows = []
    for tr in t.find_all("tr"):
        if tr.find_parent("table") is not t:              # rows of a table nested in a cell
            continue
        cells = [re.sub(r"\s+", " ", inline(td, resolve)).strip().replace("|", "\\|")
                 for td in tr.find_all(["td", "th"], recursive=False)]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def blocks(node, resolve: Resolver | None = None, depth: int = 0) -> list[str]:
    """Markdown blocks of an element and its children."""
    out: list[str] = []
    buf: list[str] = []

    def flush():
        text = re.sub(r"(?<=\S) {2,}", " ", "".join(buf)).strip()
        buf.clear()
        if text:
            out.append(text)

    for ch in (node.children if isinstance(node, Tag) else []):
        if isinstance(ch, NavigableString):
            buf.append(_space(str(ch)))
            continue
        if not isinstance(ch, Tag) or ch.name in SKIP:
            continue
        c = classes(ch)
        if "ltx_TOC" in c or "ltx_page_navbar" in c or "ltx_bibliography" in c and depth > 0:
            continue
        if ch.name == "table" and ({"ltx_equation", "ltx_eqn_table", "ltx_equationgroup"} & c):
            flush()
            maths = [m.get("alttext", "").strip() for m in ch.find_all("math")]
            tag = ch.find(class_="ltx_tag_equation")
            eq = " ".join(m for m in maths if m)
            if eq:
                out.append(f"$${eq}$$" + (f" {tag.get_text(strip=True)}" if tag else ""))
            continue
        if ch.name == "math" and ch.get("display") == "block":
            flush()
            out.append(inline(ch, resolve))
            continue
        if ch.name not in BLOCK:
            buf.append(inline(ch, resolve))
            continue
        flush()
        if ch.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = min(6, int(ch.name[1]) + 1)
            out.append("#" * level + " " + inline(ch, resolve).strip())
        elif ch.name == "table":
            md = table_md(ch, resolve)
            if md:
                out.append(md)
        elif ch.name == "figure":
            cap = ch.find("figcaption")
            inner_tables = [table_md(t, resolve) for t in ch.find_all("table")
                            if not ({"ltx_equation", "ltx_eqn_table"} & classes(t))]
            if cap:
                out.append(f"*{inline(cap, resolve).strip()}*")
            out += [t for t in inner_tables if t]
        elif ch.name in ("ul", "ol"):
            for i, li in enumerate(ch.find_all("li", recursive=False), 1):
                for tag in li.find_all(class_="ltx_tag_item", recursive=False) + \
                        li.find_all(class_="ltx_tag_itemize", recursive=False) + \
                        li.find_all(class_="ltx_tag_enumerate", recursive=False):
                    tag.extract()
                sub = blocks(li, resolve, depth + 1)
                mark = "-" if ch.name == "ul" else f"{i}."
                if sub:
                    first, rest = sub[0], sub[1:]
                    item = f"{mark} {first}" + "".join("\n\n    " + b.replace("\n", "\n    ") for b in rest)
                    out.append(item)
        elif ch.name == "blockquote":
            sub = blocks(ch, resolve, depth + 1)
            out += ["> " + b.replace("\n", "\n> ") for b in sub]
        elif ch.name == "pre":
            out.append("```\n" + ch.get_text() + "\n```")
        else:
            out += blocks(ch, resolve, depth + 1)
    flush()
    # join consecutive list items into one list
    merged: list[str] = []
    for b in out:
        if merged and re.match(r"^(-|\d+\.) ", b) and re.match(r"^(-|\d+\.) ", merged[-1].split("\n")[-1]):
            merged[-1] += "\n" + b
        else:
            merged.append(b)
    return merged


def markdown(node, resolve: Resolver | None = None) -> str:
    return "\n\n".join(b for b in blocks(node, resolve) if b.strip())


def element(el: Tag, resolve: Resolver | None = None) -> str:
    """Markdown of one element (e.g. a paragraph or a figure), not just its children."""
    wrapper = Tag(name="div")
    wrapper.append(copy.copy(el))
    return markdown(wrapper, resolve)
