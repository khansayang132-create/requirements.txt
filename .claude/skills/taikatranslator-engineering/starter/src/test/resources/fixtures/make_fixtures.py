#!/usr/bin/env python3
"""Regenerates the synthetic "service agreement" fixture set from one source.

Outputs (paths relative to src/test/resources/):
  fixtures/service-agreement.html          source of the input document
  fixtures/service-agreement.pdf           rendered by LibreOffice if available
  mocks/azure-layout-service-agreement.json  hand-authored prebuilt-layout analyzeResult
  mocks/deepl-es-service-agreement.json      protected-XML source -> Spanish
  expected/service-agreement.extraction.json canonical blocks after extraction
  expected/service-agreement.ES.structure.json DOCX structure after translation

The Azure mock is SYNTHETIC: written to match the documented response shape,
not captured from a live call. Re-record it from a real call before relying on
provider-specific details (see references/providers.md).

Usage: python3 make_fixtures.py   (run from this folder)
"""
import json
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.dirname(HERE)

PAGE = {"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch", "angle": 0}

# (role, english, spanish, box inches x0, y0, x1, y1). Role None = body.
BLOCKS = [
    ("title", "Service Agreement", "Contrato de servicios", (1.0, 1.0, 7.5, 1.5)),
    ("sectionHeading", "1. Payment Terms", "1. Condiciones de pago", (1.0, 1.8, 7.5, 2.1)),
    (None, "The client pays {amount} within 30 days of the invoice date.",
     "El cliente paga {amount} en un plazo de 30 días desde la fecha de la factura.", (1.0, 2.3, 7.5, 2.6)),
    # Right edge at 8.55 in is 0.6% past the page: exercises the documented clamp recovery.
    (None, "Questions go to billing@example.com or https://example.com/help.",
     "Las consultas van a billing@example.com o https://example.com/help.", (1.0, 2.7, 8.55, 3.0)),
    "TABLE",
    # Small box: the Spanish is 2.5x longer and must shrink to fit (text expansion).
    (None, "Total amount due", "Importe total adeudado pendiente de pago", (1.0, 4.6, 2.6, 4.85)),
    ("pageNumber", "1", "1", (4.1, 10.3, 4.4, 10.5)),
]
# Font sizes the DOCX must use, derived by hand from DocxAssembler's limits
# (title 20, heading 14, body 11, min 7, step 0.5, line spacing 1.15) and a
# fixed-advance measurer of 0.5 em. "Total amount due" -> 40-char Spanish in a
# 115 x 18 pt box fits on two lines only at 7.5 pt.
EXPECTED_SIZE = {"Service Agreement": 20.0, "1. Payment Terms": 14.0, "Total amount due": 7.5}
BODY_SIZE = 11.0

TABLE = {
    "box": (1.0, 3.3, 7.5, 4.3),
    "en": [["Item", "Price"], ["Translation", "120 EUR"], ["Review", "45 EUR"]],
    "es": [["Concepto", "Precio"], ["Traducción", "120 EUR"], ["Revisión", "45 EUR"]],
}


def poly(x0, y0, x1, y1):
    return [x0, y0, x1, y0, x1, y1, x0, y1]


def protect(text):
    """Mirror of PlaceholderProtector for the tokens this fixture uses."""
    import re
    pattern = re.compile("|".join([
        r"\{\{[^{}]+}}", r"\{[A-Za-z0-9_]+}",
        r"%(?:\d+\$)?[-+ 0#]*\d*(?:\.\d+)?[sdfiuxXeEgGc%]",
        r"https?://[^\s<>\"]*[^\s<>\".,;:!?)\]}'’”]",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    ]))
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out, last, n = [], 0, 0
    for m in pattern.finditer(text):
        out.append(esc(text[last:m.start()]))
        out.append(f'<ph id="{n}">{esc(m.group())}</ph>')
        n += 1
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


def build():
    content, paragraphs, tables, deepl = [], [], [], {}
    offset = 0

    def add(text):
        nonlocal offset
        start = offset
        content.append(text)
        offset += len(text) + 1  # "\n" separator
        return {"offset": start, "length": len(text)}

    expected_blocks, expected_docx = [], []
    pid = 0
    for b in BLOCKS:
        if b == "TABLE":
            t_start = offset
            cells = []
            rows, cols = len(TABLE["en"]), len(TABLE["en"][0])
            x0, y0, x1, y1 = TABLE["box"]
            for r in range(rows):
                for c in range(cols):
                    text = TABLE["en"][r][c]
                    span = add(text)
                    cx0 = x0 + (x1 - x0) * c / cols
                    cy0 = y0 + (y1 - y0) * r / rows
                    region = [{"pageNumber": 1, "polygon": poly(cx0, cy0, cx0 + (x1 - x0) / cols, cy0 + (y1 - y0) / rows)}]
                    cells.append({"kind": "columnHeader" if r == 0 else "content", "rowIndex": r, "columnIndex": c,
                                  "content": text, "boundingRegions": region, "spans": [span]})
                    # Azure also lists cell text as paragraphs; the mapper must drop these.
                    paragraphs.append({"content": text, "boundingRegions": region, "spans": [span]})
                    deepl[protect(text)] = protect(TABLE["es"][r][c])
            tables.append({"rowCount": rows, "columnCount": cols, "cells": cells,
                           "boundingRegions": [{"pageNumber": 1, "polygon": poly(*TABLE["box"])}],
                           "spans": [{"offset": t_start, "length": offset - 1 - t_start}]})
            expected_blocks.append({"type": "table", "id": "t1", "rows": rows, "columns": cols, "cells": TABLE["en"]})
            expected_docx.append({"type": "table", "rows": rows, "columns": cols, "cells": TABLE["es"]})
            continue
        role, en, es, box = b
        para = {"content": en, "boundingRegions": [{"pageNumber": 1, "polygon": poly(*box)}], "spans": [add(en)]}
        if role:
            para["role"] = role
        paragraphs.append(para)
        deepl[protect(en)] = protect(es)
        pid += 1
        canonical_role = {"title": "TITLE", "sectionHeading": "HEADING", "pageNumber": "PAGE_NUMBER"}.get(role, "BODY")
        expected_blocks.append({"type": "paragraph", "id": f"p{pid}", "role": canonical_role, "text": en})
        if canonical_role != "PAGE_NUMBER":
            style = {"TITLE": "Title", "HEADING": "Heading1"}.get(canonical_role)
            expected_docx.append({"type": "paragraph", "style": style, "text": es,
                                  "fontSize": EXPECTED_SIZE.get(en, BODY_SIZE)})

    result = {
        "apiVersion": "2024-11-30",
        "modelId": "prebuilt-layout",
        "content": "\n".join(content),
        "pages": [PAGE],
        "paragraphs": paragraphs,
        "tables": tables,
    }
    return result, deepl, expected_blocks, expected_docx


def write_json(rel, data):
    path = os.path.join(RES, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_html():
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in TABLE["en"])
    body = []
    for b in BLOCKS:
        if b == "TABLE":
            body.append(f'<table border="1">{rows}</table>')
            continue
        role, en, _, _ = b
        tag = {"title": "h1", "sectionHeading": "h2", "pageNumber": "p"}.get(role, "p")
        body.append(f"<{tag}>{en}</{tag}>")
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>Service Agreement</title></head><body>"
            + "".join(body) + "</body></html>\n")
    path = os.path.join(HERE, "service-agreement.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def render_pdf(html_path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("LibreOffice not found: service-agreement.pdf NOT regenerated")
        return
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "pdf:writer_web_pdf_Export", "--outdir", HERE, html_path],
                       check=True, capture_output=True, timeout=180)
    print("rendered", os.path.join(HERE, "service-agreement.pdf"))


if __name__ == "__main__":
    result, deepl, blocks, docx = build()
    write_json("mocks/azure-layout-service-agreement.json", {"status": "succeeded", "analyzeResult": result})
    write_json("mocks/deepl-es-service-agreement.json", deepl)
    write_json("expected/service-agreement.extraction.json", {"pages": 1, "blocks": blocks})
    write_json("expected/service-agreement.ES.structure.json", {"targetLang": "ES", "body": docx,
                                                                 "section": {"pageWidthTwips": 12240, "pageHeightTwips": 15840, "orientation": "portrait"}})
    render_pdf(write_html())
