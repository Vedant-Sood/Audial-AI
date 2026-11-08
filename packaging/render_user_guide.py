"""Render the Kandha user guide (Markdown) as a self-contained HTML page, with the standard library only.

Stock Windows has no program for .md files, so the Start-menu "Kandha user guide" opens this HTML
copy in the default browser instead. AccessibilityAI.spec renders it at build time; by hand:

    python packaging/render_user_guide.py docs/kandha/USER_GUIDE.md build/USER_GUIDE.html

It covers the Markdown the guide uses: headings, paragraphs, block quotes, bullet and numbered lists,
pipe tables, fenced code, rules, **bold**, *italic*, `code` and [links](url). Anything else stays
plain, escaped text. The page has no script and loads nothing from the network; the only file it
asks for is the bundled Atkinson Hyperlegible font, and it reads fine without it.
"""
import argparse
import html
from pathlib import Path
import re

# From _internal/docs/kandha/ to the font Kandha already ships (browser/kandha/fonts).
FONT_DIR = "../../browser/kandha/fonts"

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([\w+-]*)")
QUOTE = re.compile(r"^ {0,3}> ?")
RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_ITEM = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])(?:[ \t]+(.*)|$)")
TABLE_RULE = re.compile(r"^ {0,3}\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$")
CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
ITALIC = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])", re.S)
DEVANAGARI = re.compile(r"[ऀ-ॿ]+")
SCHEME = re.compile(r"^\s*([a-z][\w+.-]*):", re.I)
SAFE_SCHEMES = {"http", "https", "mailto"}

STYLE = """
@font-face { font-family: "Atkinson Hyperlegible"; src: url("{fonts}/AtkinsonHyperlegible-Regular.ttf"); font-weight: 400; font-style: normal; }
@font-face { font-family: "Atkinson Hyperlegible"; src: url("{fonts}/AtkinsonHyperlegible-Bold.ttf"); font-weight: 700; font-style: normal; }
@font-face { font-family: "Atkinson Hyperlegible"; src: url("{fonts}/AtkinsonHyperlegible-Italic.ttf"); font-weight: 400; font-style: italic; }
@font-face { font-family: "Atkinson Hyperlegible"; src: url("{fonts}/AtkinsonHyperlegible-BoldItalic.ttf"); font-weight: 700; font-style: italic; }
:root { --bg: #fffdf8; --fg: #1d1b18; --muted: #5b554c; --line: #cfc6b6; --accent: #8a4500; --panel: #f4ede1; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #16140f; --fg: #f2eee6; --muted: #c9c1b2; --line: #4f493f; --accent: #ffb870; --panel: #25211a; }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 1.125rem/1.6 "Atkinson Hyperlegible", "Segoe UI", system-ui, sans-serif; }
main, footer { max-width: 46rem; margin: 0 auto; padding: 1.5rem 1rem; }
h1 { font-size: 2rem; line-height: 1.2; margin: 1rem 0 1.25rem; }
h2 { font-size: 1.45rem; line-height: 1.25; margin: 2.5rem 0 .75rem; padding-top: .5rem; border-top: 1px solid var(--line); }
h3 { font-size: 1.2rem; margin: 2rem 0 .5rem; }
p, ul, ol { margin: 0 0 1rem; }
li { margin: .3rem 0; }
a { color: var(--accent); text-underline-offset: .15em; }
a:focus-visible, .table:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
blockquote { margin: 1.5rem 0; padding: .75rem 1rem; border-left: 4px solid var(--accent); background: var(--panel); }
blockquote > :last-child { margin-bottom: 0; }
code, pre { font-family: "Cascadia Mono", Consolas, ui-monospace, monospace; font-size: .95em; }
code { background: var(--panel); padding: .05em .3em; border-radius: 4px; overflow-wrap: anywhere; }
pre { background: var(--panel); padding: .75rem 1rem; overflow-x: auto; }
pre code { padding: 0; }
.table { overflow-x: auto; margin: 0 0 1.25rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid var(--line); padding: .45rem .6rem; text-align: left; vertical-align: top; }
th { background: var(--panel); }
nav ul { padding-left: 1.25rem; }
hr { border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }
footer { color: var(--muted); font-size: 1rem; border-top: 1px solid var(--line); }
@media (max-width: 30rem) { body { font-size: 1.05rem; } h1 { font-size: 1.7rem; } }
@media print { a { color: inherit; } .table { overflow: visible; } }
"""


def _emphasis(text):
    text = html.escape(text, quote=False)
    text = LINK.sub(_link, text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = ITALIC.sub(r"<em>\1</em>", text)
    # Mark Hindi words so a screen reader switches voice; never inside a tag's attributes.
    return "".join(part if part.startswith("<") else DEVANAGARI.sub(lambda m: f'<span lang="hi">{m.group(0)}</span>', part)
                   for part in re.split(r"(<[^>]*>)", text))


def _link(match):
    label, href = match.group(1), html.unescape(match.group(2))
    scheme = SCHEME.match(href)
    if scheme and scheme.group(1).lower() not in SAFE_SCHEMES:
        return match.group(0)                      # leave javascript: and friends as text
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def inline(text):
    """Escape `text` and apply code spans, links, bold and italic."""
    out, pos = [], 0
    for match in CODE_SPAN.finditer(text):
        out.append(_emphasis(text[pos:match.start()]))
        out.append(f"<code>{html.escape(match.group(2).strip(), quote=False)}</code>")
        pos = match.end()
    out.append(_emphasis(text[pos:]))
    return "".join(out)


def _starts_block(line):
    return bool(HEADING.match(line) or FENCE.match(line) or QUOTE.match(line) or RULE.match(line)
                or LIST_ITEM.match(line))


def _cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", row)]


def _table(lines):
    head, rule, body = _cells(lines[0]), _cells(lines[1]), [_cells(line) for line in lines[2:]]
    align = ["center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else ""
             for c in rule]

    def cell(tag, text, index, scope=""):
        style = f' style="text-align: {align[index]}"' if index < len(align) and align[index] else ""
        return f"<{tag}{scope}{style}>{inline(text)}</{tag}>"

    label = html.escape(", ".join(re.sub(r"[*`]", "", c) for c in head), quote=True)
    rows = ["<tr>" + "".join(cell("th", text, i, ' scope="col"') for i, text in enumerate(head)) + "</tr>"]
    out = [f'<div class="table" role="region" aria-label="Table: {label}" tabindex="0">', "<table>",
           "<thead>", *rows, "</thead>", "<tbody>"]
    for row in body:
        row = (row + [""] * len(head))[:len(head)]
        out.append("<tr>" + "".join(cell("td", text, i) for i, text in enumerate(row)) + "</tr>")
    out += ["</tbody>", "</table>", "</div>"]
    return "\n".join(out)


def _list(lines, start):
    """Parse a list starting at lines[start]; return (html, next index)."""
    first = LIST_ITEM.match(lines[start])
    indent, ordered = len(first.group(1)), first.group(2)[0].isdigit()
    items, loose, i = [], False, start
    while i < len(lines):
        line = lines[i]
        item = LIST_ITEM.match(line)
        if item and len(item.group(1)) == indent and item.group(2)[0].isdigit() == ordered:
            width = item.start(3) if item.group(3) is not None else len(line)
            items.append({"width": width, "lines": [item.group(3) or ""],
                          "number": int(item.group(2)[:-1]) if ordered else None})
            i += 1
            continue
        if not line.strip():
            following = lines[i + 1] if i + 1 < len(lines) else ""
            nested = following.strip() and len(following) - len(following.lstrip()) >= items[-1]["width"]
            again = LIST_ITEM.match(following)
            if nested or (again and len(again.group(1)) == indent and again.group(2)[0].isdigit() == ordered):
                loose = True
                items[-1]["lines"].append("")
                i += 1
                continue
            break
        leading = len(line) - len(line.lstrip())
        if leading >= items[-1]["width"] or (leading > indent and not LIST_ITEM.match(line)):
            items[-1]["lines"].append(line[min(leading, items[-1]["width"]):])
        elif items[-1]["lines"][-1].strip() and not _starts_block(line):
            items[-1]["lines"].append(line.strip())          # lazy continuation of the item's paragraph
        else:
            break
        i += 1
    out = []
    for item in items:
        content = item["lines"]
        if not loose and not any(_starts_block(line) for line in content[1:]):
            body = inline("\n".join(line.strip() for line in content))
        else:
            body = "\n".join(blocks(content))
        out.append(f"<li>{body}</li>")
    tag = "ol" if ordered else "ul"
    start_at = items[0]["number"] if ordered and items[0]["number"] != 1 else None
    opening = f'<{tag} start="{start_at}">' if start_at is not None else f"<{tag}>"
    return "\n".join([opening, *out, f"</{tag}>"]), i


def blocks(lines, headings=None):
    """Markdown lines -> list of HTML block strings. Headings found are appended to `headings`."""
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = FENCE.match(line)
        if fence:
            marker, code, i = fence.group(1), [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>")
            continue
        heading = HEADING.match(line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            slug = _slug(text, headings)
            if headings is not None:
                headings.append((level, slug, text))
            out.append(f'<h{level} id="{slug}">{inline(text)}</h{level}>')
            i += 1
            continue
        if RULE.match(line):
            out.append("<hr>")
            i += 1
            continue
        if QUOTE.match(line):
            quoted = []
            while i < len(lines) and lines[i].strip() and (QUOTE.match(lines[i]) or not _starts_block(lines[i])):
                quoted.append(QUOTE.sub("", lines[i], count=1))
                i += 1
            out.append("<blockquote>\n" + "\n".join(blocks(quoted, headings)) + "\n</blockquote>")
            continue
        if "|" in line and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
            rows = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if LIST_ITEM.match(line):
            listing, i = _list(lines, i)
            out.append(listing)
            continue
        paragraph = []
        while i < len(lines) and lines[i].strip() and (not paragraph or not _starts_block(lines[i])):
            if paragraph and "|" in lines[i] and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
                break
            paragraph.append(lines[i])
            i += 1
        parts = []
        for n, raw in enumerate(paragraph):
            text = raw.strip()
            hard = n < len(paragraph) - 1 and (raw.endswith("  ") or text.endswith("\\"))   # a line break
            parts.append((text[:-1] if hard and text.endswith("\\") else text) + ("\0" if hard else ""))
        out.append("<p>" + inline("\n".join(parts)).replace("\0", "<br>") + "</p>")
    return out


def _slug(text, seen):
    plain = re.sub(r"[*`_\[\]()]", "", text)
    slug = re.sub(r"[^\w-]+", "-", plain.lower(), flags=re.U).strip("-") or "section"
    taken = {s for _, s, _ in (seen or [])}
    base, n = slug, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def render(markdown, source_name="USER_GUIDE.md"):
    """The whole HTML page for a Markdown document."""
    headings = []
    body = blocks(markdown.replace("\r\n", "\n").replace("\t", "    ").split("\n"), headings)
    title = next((re.sub(r"[*`]", "", text) for level, _, text in headings if level == 1), "User guide")
    sections = [(slug, text) for level, slug, text in headings if level == 2]
    if len(sections) >= 3:
        nav = ['<nav aria-label="Contents">', "<h2 id=\"contents\">Contents</h2>", "<ul>"]
        nav += [f'<li><a href="#{slug}">{inline(text)}</a></li>' for slug, text in sections]
        nav += ["</ul>", "</nav>"]
        first_section = next((n for n, block in enumerate(body) if block.startswith("<h2")), len(body))
        body[first_section:first_section] = ["\n".join(nav)]
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        # Nothing on this page may reach the network: no script, no remote font or image.
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
        "font-src 'self' file:; img-src 'self' file: data:\">",
        f"<title>{html.escape(title)}</title>",
        "<style>" + STYLE.replace("{fonts}", FONT_DIR) + "</style>",
        "</head>",
        "<body>",
        "<main>",
        *body,
        "</main>",
        "<footer><p>Made from <code>" + html.escape(source_name) + "</code> when this copy of Kandha was built. "
        "It opens in your web browser and works offline.</p></footer>",
        "</body>",
        "</html>",
        "",
    ])


def write(source, output):
    """Render the Markdown file `source` to `output`; return the output path."""
    source, output = Path(source), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(source.read_text(encoding="utf-8"), source.name), encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    print(write(args.source, args.output))


if __name__ == "__main__":
    main()
