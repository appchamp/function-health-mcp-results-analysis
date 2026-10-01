#!/usr/bin/env python3
"""
Convert a report's Markdown to print-styled HTML for render.sh.

The .md is the source of truth; the .html is a build artifact, so it can't drift from
the .md the way the v3 report.html did. Handles the subset the reports use: YAML front
matter (skipped), headings, pipe tables, bullet and numbered lists, fenced code,
horizontal rules, paragraphs, and inline **bold**, *italic* and `code`.

Usage:  python3 md2html.py ../reports/<name>.md   # writes ../reports/<name>.html
"""

import html
import re
import sys
from pathlib import Path

# Print styling carried over from the v3 report.html.
CSS = """
@page { size: Letter; margin: 15mm 14mm 15mm 14mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; box-sizing: border-box; }
html { font-size: 10pt; }
body { font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
       color: #1a1d21; line-height: 1.46; margin: 0; }
h1 { font-size: 21pt; margin: 0 0 4pt; letter-spacing: -0.4pt; }
h1.part { font-size: 15pt; margin-top: 22pt; break-before: page; page-break-before: page; }
h2 { font-size: 12.5pt; margin: 19pt 0 6pt; padding-bottom: 3.5pt;
     border-bottom: 1.5px solid #1a1d21; letter-spacing: -0.2pt;
     break-after: avoid; page-break-after: avoid; }
h3 { font-size: 10.5pt; margin: 12pt 0 4pt; color: #33383e;
     break-after: avoid; page-break-after: avoid; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt; padding-left: 16pt; }
li { margin-bottom: 2.5pt; }
strong { font-weight: 650; }
em { color: #555b63; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 0.9em; }
hr { border: none; border-top: 1px solid #e0e3e8; margin: 12pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt;
        font-size: 8.9pt; break-inside: avoid; page-break-inside: avoid; }
th { text-align: left; font-size: 7.6pt; text-transform: uppercase; letter-spacing: 0.45pt;
     color: #5c636c; font-weight: 600; border-bottom: 1.2px solid #9ba1a9; padding: 3.5pt 6pt 3.5pt 0; }
td { padding: 4pt 6pt 4pt 0; border-bottom: 1px solid #e6e8ec; vertical-align: top; }
tr:last-child td { border-bottom: none; }
pre { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.6pt;
      background: #f4f5f7; border: 1px solid #e0e3e8; border-radius: 3px;
      padding: 8pt 10pt; margin: 7pt 0; line-height: 1.7; white-space: pre; break-inside: avoid; }
footer, p.footer { margin-top: 16pt; padding-top: 6pt; border-top: 1px solid #d8dbe0;
                   font-size: 7.8pt; color: #7a808a; }
"""


def inline(text):
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        p = html.escape(p, quote=False)
        p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", p)
        out.append(p)
    return "".join(out)


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(md):
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        lines = lines[end + 1 :]

    out, title, h1_seen, i = [], None, False, 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
        elif s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1 : j])) + "</pre>")
            i = j + 1
        elif re.fullmatch(r"-{3,}", s):
            out.append("<hr>")
            i += 1
        elif m := re.match(r"(#{1,6})\s+(.*)", s):
            level, text = len(m.group(1)), m.group(2)
            if level == 1:
                title = title or text
                cls = ' class="part"' if h1_seen else ""
                h1_seen = True
                out.append(f"<h1{cls}>{inline(text)}</h1>")
            else:
                out.append(f"<h{level}>{inline(text)}</h{level}>")
            i += 1
        elif s.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|?[\s:|-]+\|?", lines[i + 1].strip()):
            head = split_row(s)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            t = ["<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"]
            for r in rows:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("".join(t) + "</tbody></table>")
            i = j
        elif re.match(r"([-*]|\d+\.)\s", s):
            ordered = bool(re.match(r"\d+\.", s))
            tag = "ol" if ordered else "ul"
            items = []
            j = i
            while j < len(lines) and re.match(r"([-*]|\d+\.)\s", lines[j].strip()):
                items.append(re.sub(r"^([-*]|\d+\.)\s+", "", lines[j].strip()))
                j += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            i = j
        else:
            para = [s]
            j = i + 1
            while j < len(lines) and lines[j].strip() and not re.match(r"(#|\||```|-{3,}$|[-*]\s|\d+\.\s)", lines[j].strip()):
                para.append(lines[j].strip())
                j += 1
            text = " ".join(para)
            cls = ' class="footer"' if text.startswith("*") and text.endswith("*") else ""
            out.append(f"<p{cls}>{inline(text)}</p>")
            i = j

    doc_title = html.escape(re.sub(r"[*`]", "", title or "Report"))
    return (
        f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{doc_title}</title><style>{CSS}</style></head>\n<body>\n"
        + "\n".join(out)
        + "\n</body></html>\n"
    )


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: md2html.py <report.md>")
    src = Path(sys.argv[1])
    dst = src.with_suffix(".html")
    dst.write_text(convert(src.read_text()))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
