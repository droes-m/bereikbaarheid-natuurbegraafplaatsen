"""Convert docs/paper_bereikbaarheid_natuurbegraafplaatsen.md to a publication-ready A4 PDF via headless Chrome."""

from __future__ import annotations

import base64
import html
import re
import subprocess
import sys
from pathlib import Path

CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _inline_md(text: str) -> str:
    """Convert basic inline Markdown (bold, italic, code, links) to HTML."""
    # Escape HTML first
    s = html.escape(text, quote=False)
    # Links: [label](url)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    # Inline code: `code`
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    # Bold: **text**
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    # Italic: *text*
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def _embed_image_data_uri(img_path: Path) -> str:
    raw = img_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def markdown_to_html_body(md_text: str, base_dir: Path) -> str:
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    fig_counter = 0

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if stripped == "---":
            out.append("<hr />")
            i += 1
            continue

        # Headings
        m_head = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m_head:
            level = len(m_head.group(1))
            content = _inline_md(m_head.group(2))
            if level == 1:
                out.append(f'<h1 class="paper-title">{content}</h1>')
            else:
                out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Image on its own line -> styled figure with caption
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m_img:
            fig_counter += 1
            alt, rel = m_img.group(1), m_img.group(2)
            img_path = (base_dir / rel).resolve()
            src = _embed_image_data_uri(img_path)
            out.append(
                f'<figure class="paper-figure">'
                f'<img src="{src}" alt="{html.escape(alt)}" />'
                f"<figcaption><strong>Figuur {fig_counter}.</strong> {_inline_md(alt)}</figcaption>"
                f"</figure>"
            )
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            q_lines = []
            while i < n and lines[i].strip().startswith(">"):
                q_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f'<blockquote class="callout">{_inline_md(" ".join(q_lines))}</blockquote>')
            continue

        # Markdown table
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            align_cells = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            aligns = []
            for a in align_cells:
                if a.endswith(":") and a.startswith(":"):
                    aligns.append("center")
                elif a.endswith(":"):
                    aligns.append("right")
                else:
                    aligns.append("left")
            i += 2
            body_rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                body_rows.append(cells)
                i += 1

            tbl = ['<div class="table-wrap"><table><thead><tr>']
            for idx, h in enumerate(header_cells):
                al = aligns[idx] if idx < len(aligns) else "left"
                tbl.append(f'<th style="text-align:{al}">{_inline_md(h)}</th>')
            tbl.append("</tr></thead><tbody>")
            for row in body_rows:
                tbl.append("<tr>")
                for idx, cell in enumerate(row):
                    al = aligns[idx] if idx < len(aligns) else "left"
                    tbl.append(f'<td style="text-align:{al}">{_inline_md(cell)}</td>')
                tbl.append("</tr>")
            tbl.append("</tbody></table></div>")
            out.append("".join(tbl))
            continue

        # Unordered list
        if stripped.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline_md(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                item_txt = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append(f"<li>{_inline_md(item_txt)}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        # Paragraph (collect consecutive text lines)
        para_lines = []
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", ">", "|", "- ", "---", "!["))
            and not re.match(r"^\d+\.\s+", lines[i].strip())
        ):
            para_lines.append(lines[i].strip())
            i += 1
        para_text = " ".join(para_lines)
        # Style subtitle/meta right under h1 cleanly
        if len(out) == 1 and out[0].startswith('<h1 class="paper-title">'):
            out.append(f'<p class="paper-subtitle">{_inline_md(para_text)}</p>')
        elif len(out) == 2 and out[1].startswith('<p class="paper-subtitle">'):
            out.append(f'<p class="paper-meta">{_inline_md(para_text)}</p>')
        else:
            out.append(f"<p>{_inline_md(para_text)}</p>")

    return "\n".join(out)


def build_pdf(md_path: Path, pdf_path: Path) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    body_html = markdown_to_html_body(md_text, base_dir=md_path.parent)

    full_html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8" />
  <title>Ruimtelijke bereikbaarheid van natuurbegraafplaatsen in Vlaanderen</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 17mm 20mm 17mm;
      @bottom-left {{
        content: "Bereikbaarheid van natuurbegraafplaatsen in Vlaanderen";
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
        font-size: 7.5pt;
        color: #6b7280;
      }}
      @bottom-right {{
        content: "Pagina " counter(page) " van " counter(pages);
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
        font-size: 7.5pt;
        color: #6b7280;
      }}
    }}
    @page :first {{
      @bottom-left {{ content: none; }}
    }}
    body {{
      font-family: "Georgia", "Times New Roman", serif;
      font-size: 10pt;
      line-height: 1.52;
      color: #1f2933;
      margin: 0;
      padding: 0;
    }}
    h1, h2, h3, h4, th, figcaption, .paper-subtitle, .paper-meta {{
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    }}
    h1.paper-title {{
      font-size: 20pt;
      line-height: 1.2;
      color: #0f3d2e;
      margin: 0 0 6pt 0;
      padding-bottom: 6pt;
      border-bottom: 2.5px solid #0f3d2e;
    }}
    p.paper-subtitle {{
      font-size: 11pt;
      color: #334e68;
      margin: 0 0 4pt 0;
      line-height: 1.35;
    }}
    p.paper-meta {{
      font-size: 8.8pt;
      color: #627d98;
      margin: 0 0 12pt 0;
    }}
    h2 {{
      font-size: 13pt;
      color: #0f3d2e;
      margin: 18pt 0 7pt 0;
      padding-bottom: 3pt;
      border-bottom: 1px solid #d9e2ec;
      page-break-after: avoid;
      break-after: avoid;
    }}
    h3 {{
      font-size: 10.6pt;
      color: #243b53;
      margin: 12pt 0 5pt 0;
      page-break-after: avoid;
      break-after: avoid;
    }}
    p {{
      margin: 0 0 8pt 0;
      text-align: justify;
      hyphens: auto;
    }}
    ul, ol {{
      margin: 4pt 0 9pt 0;
      padding-left: 18pt;
    }}
    li {{
      margin-bottom: 3.5pt;
    }}
    hr {{
      border: none;
      border-top: 1px solid #d9e2ec;
      margin: 12pt 0;
    }}
    blockquote.callout {{
      margin: 10pt 0 12pt 0;
      padding: 8pt 12pt;
      background: #f0f7f4;
      border-left: 3.5px solid #1b7a58;
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      font-size: 8.8pt;
      line-height: 1.45;
      color: #243b53;
      break-inside: avoid;
    }}
    code {{
      font-family: "SFMono-Regular", Menlo, Consolas, monospace;
      font-size: 8.5pt;
      background: #f1f5f9;
      padding: 1pt 3.5pt;
      border-radius: 3px;
      color: #0f3d2e;
    }}
    a {{
      color: #0f5132;
      text-decoration: none;
    }}
    .table-wrap {{
      margin: 10pt 0 12pt 0;
      break-inside: avoid;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      font-size: 8.3pt;
      line-height: 1.35;
    }}
    thead th {{
      background: #0f3d2e;
      color: #ffffff;
      font-weight: 600;
      padding: 5.5pt 6pt;
      border: 0.5px solid #0f3d2e;
    }}
    tbody td {{
      padding: 4.5pt 5.5pt;
      border-bottom: 0.5px solid #d9e2ec;
      vertical-align: top;
    }}
    tbody td[style*="text-align:right"] {{
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    tbody tr:nth-child(even) {{
      background: #f8fafc;
    }}
    figure.paper-figure {{
      margin: 12pt 0 14pt 0;
      text-align: center;
      break-inside: avoid;
    }}
    figure.paper-figure img {{
      max-width: 100%;
      height: auto;
      border: 0.5px solid #e2e8f0;
      border-radius: 3px;
    }}
    figure.paper-figure figcaption {{
      margin-top: 5pt;
      font-size: 8.4pt;
      color: #486581;
      text-align: left;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
{body_html}
</body>
</html>
"""

    tmp_html = pdf_path.with_suffix(".tmp.html")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_html.write_text(full_html, encoding="utf-8")

    try:
        cmd = [
            str(CHROME_BIN),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            f"file://{tmp_html.resolve()}",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        tmp_html.unlink(missing_ok=True)

    print(f"PDF aangemaakt: {pdf_path} ({pdf_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    md = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/paper_bereikbaarheid_natuurbegraafplaatsen.md")
    pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("outputs/paper_bereikbaarheid_natuurbegraafplaatsen.pdf")
    build_pdf(md, pdf)
