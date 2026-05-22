"""
Spike benchmark for issue #15: which method most reliably catalogs Sheets and the Sheet Index in a Drawing Set?

Methods probed per PDF:
  (a) PDF bookmarks (outline) at depth 2 — expects `<SHEET_NUM> - <TITLE>`
  (b) Vector text on the Sheet Index page (early-page scan for "SHEET INDEX" / "DRAWING INDEX" etc.)
  (c) Vector text in a title-block rectangle on each page (cross-check against bookmarks)

Run:
  python scripts/probe_drawing_extraction.py <pdf> [<pdf> ...]

Findings inform ADR-0014 (drawing-index extraction method). See issue #15.
"""
import fitz, re, sys, json
from pathlib import Path

BOOKMARK_RE = re.compile(r"^([A-Z]{1,4}[-\.]?[\d\.]+[a-z]?)\s*[-–]\s*(.+)$")
INDEX_PAGE_RE = re.compile(
    # Generic forms plus discipline-prefixed forms ("CIVIL INDEX", "LANDSCAPE INDEX",
    # "FRONT END INDEX", "ARCHITECTURAL SITE INDEX", etc.) — used by firms like the
    # one behind the Juvenile fixture, where the index page has multiple per-discipline
    # index sections on the same sheet rather than one umbrella "SHEET INDEX" table.
    r"\b("
    r"SHEET\s+INDEX|DRAWING\s+INDEX|INDEX\s+OF\s+(DRAWINGS|SHEETS)|SHEET\s+LIST|LIST\s+OF\s+DRAWINGS"
    r"|[A-Z][A-Z\s/&]{1,40}?\s+INDEX"
    r")\b",
    re.I,
)


def method_a_bookmarks(doc):
    sheets = []
    for level, title, page in doc.get_toc():
        if level != 2:
            continue
        m = BOOKMARK_RE.match(title.strip())
        if m:
            sheets.append({"sheet_no": m.group(1), "title": m.group(2).strip(), "page": page})
    return sheets


def method_b_index_page(doc):
    for i in range(min(15, doc.page_count)):
        txt = doc[i].get_text("text") or ""
        if INDEX_PAGE_RE.search(txt):
            return {"page": i + 1, "char_count": len(txt), "vector_text": True}
    return None


def method_c_title_block_crosscheck(doc, bookmark_sheets, sample=20):
    if not bookmark_sheets:
        return None
    sample_sheets = bookmark_sheets[:sample]
    hits = 0
    for s in sample_sheets:
        page = doc[s["page"] - 1]
        w, h = page.rect.width, page.rect.height
        rect_br = fitz.Rect(w * 0.80, h * 0.70, w, h)
        rect_bottom = fitz.Rect(0, h * 0.88, w, h)
        combined = (page.get_textbox(rect_br) or "") + " " + (page.get_textbox(rect_bottom) or "")
        if s["sheet_no"] in combined:
            hits += 1
    return {"sample_size": len(sample_sheets), "agreement": hits, "rate": round(hits / len(sample_sheets), 2)}


def probe(pdf_path):
    doc = fitz.open(pdf_path)
    bookmarks = method_a_bookmarks(doc)
    result = {
        "pdf": Path(pdf_path).name,
        "pages": doc.page_count,
        "method_a_bookmarks": {"count": len(bookmarks), "sample": bookmarks[:3]},
        "method_b_index_page": method_b_index_page(doc),
        "method_c_titleblock_crosscheck": method_c_title_block_crosscheck(doc, bookmarks),
    }
    doc.close()
    return result


if __name__ == "__main__":
    results = [probe(p) for p in sys.argv[1:]]
    print(json.dumps(results, indent=2, default=str))
