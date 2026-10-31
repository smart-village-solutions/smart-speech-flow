#!/usr/bin/env python3
"""Render the German KasselDIALOG Markdown pages as an A4 landscape draft PDF.

Requires ReportLab: python -m pip install reportlab
Run from any directory: python docs/user-guide/build_pdf.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from PIL import Image

from guide_graphics import draw_graphic


ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"
SCREENSHOTS = ROOT / "screenshots"
OUTPUT = ROOT / "kasseldialog-nutzerdokumentation-entwurf.pdf"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
PAGE_W, PAGE_H = landscape(A4)

BLUE = colors.HexColor("#1D639D")
DEEP = colors.HexColor("#103F67")
CYAN = colors.HexColor("#73D8E5")
PALE = colors.HexColor("#EAF5FA")
WHITE = colors.white
INK = colors.HexColor("#183247")

# Labels correspond to docs/user-guide/screenshot-checklist.md.
PLACEHOLDERS: dict[int, list[tuple[str, str]]] = {
    1: [("G01", "Titelmotiv oder freigegebene Gesprächsansicht")],
    2: [("G02", "Übersicht beider Gesprächsseiten")],
    3: [("G03", "Vier Symbole der Vorbereitung")],
    4: [("P00", "Einladungsemail"), ("P01", "Zwischenseite"), ("P02", "Passwort festlegen")],
    5: [("P03", "Anmeldeseite"), ("S01", "Login"), ("S02", "Organisationsauswahl")],
    6: [("S03", "Gesprächsübersicht"), ("S04", "Warnung bei laufendem Gespräch")],
    7: [("S05", "Einladung mit Code, Link und QR-Code")],
    8: [("S05", "Einladung"), ("S06", "Sprachauswahl des Gastes"), ("S07/S08", "Infoseite mit/ohne Speicherfrage")],
    9: [("S09", "Laufende Gesprächsansicht")],
    10: [("S10", "Mikrofon vor und während der Eingabe")],
    11: [("S10", "Aufnahme senden"), ("S11", "Erkannte eigene Nachricht")],
    12: [("S12", "Geöffnete Texteingabe")],
    13: [("S13a", "Ansicht der Mitarbeitenden"), ("S13b", "Passende Gästeansicht")],
    14: [("S14", "Nachricht mit Wiedergabe")],
    16: [("S15", "Gespräch beenden und bestätigen")],
    17: [("G04", "Sprache → Text → Übersetzung → Ausgabe")],
    21: [("S07/S08", "Speicherfrage je Organisationseinstellung")],
    25: [("S16", "Feedbackformular")],
}

# Existing screenshots are reused where they show the same control from the
# relevant perspective. Empty prefixes identify assets still to be supplied.
# Each entry is (checklist ID, caption, filename prefix, image index).
MEDIA: dict[int, list[tuple[str, str, str | None, int]]] = {
    1: [("S13a", "KasselDIALOG im Gespräch", "S13a", 0)],
    6: [("S03", "Gesprächsübersicht", "S03", 0), ("S04", "Warnung bei laufendem Gespräch", "S04", 0)],
    7: [("S05", "Einladung mit Code und QR-Code", "S05", 0)],
    8: [("S05", "Einladung", "S05", 0), ("S06", "Sprachauswahl", "S06", 0), ("S07", "Infoseite mit Speicherfrage", "S07", 0), ("S08", "Infoseite ohne Speicherfrage", "S08", 0)],
    9: [("S13a", "Gesprächsansicht der Mitarbeitenden", "S13a", 0)],
    10: [("S10", "Aufnahme läuft · Gästeansicht", "S10", 0), ("S10", "Aufnahme gesendet · Gästeansicht", "S10", 1)],
    11: [("S10", "Gesendete Nachricht · Gästeansicht", "S10", 1), ("S11", "Nachricht der Mitarbeitenden", "S11", 0)],
    12: [("S12", "Geöffnete Texteingabe · Gästeansicht", "S12", 0)],
    13: [("S13a", "Ansicht der Mitarbeitenden", "S13a", 0), ("S13b", "Passende Gästeansicht", "S13b", 0)],
    14: [("S11", "Nachricht mit Wiedergabe", "S11", 0)],
    16: [("S15", "Bestätigung zum Beenden", "S15", 0)],
    21: [("S07", "Infoseite mit Speicherfrage", "S07", 0), ("S08", "Infoseite ohne Speicherfrage", "S08", 0)],
    25: [("S16", "Feedbackformular auf Deutsch", "S16", 0)],
}


def setup_fonts() -> None:
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")


def markup(value: str) -> str:
    """Convert only the inline Markdown constructs used by these 26 pages."""
    value = html.escape(value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#73D8E5">\1</link>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    return value


def parse_page(path: Path) -> tuple[str, list[tuple[str, object]]]:
    raw = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    lines = raw.splitlines()
    title = lines[0].removeprefix("# ")
    blocks: list[tuple[str, object]] = []
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("| "):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("| "):
                cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        if re.match(r"^\d+\. ", line):
            blocks.append(("step", line))
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("| ") and not re.match(r"^\d+\. ", lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        blocks.append(("paragraph", " ".join(paragraph)))
    return title, blocks


def paragraph_style(font_size: float, ink: colors.Color, *, bold: bool = False) -> ParagraphStyle:
    return ParagraphStyle(
        "body",
        fontName="DejaVu-Bold" if bold else "DejaVu",
        fontSize=font_size,
        leading=font_size * 1.42,
        textColor=ink,
        alignment=TA_LEFT,
        spaceAfter=0,
        allowWidows=0,
        allowOrphans=0,
    )


def block_height(block: tuple[str, object], width: float, size: float, color: colors.Color) -> float:
    kind, value = block
    if kind == "table":
        rows = value
        return sum(max(30, max(Paragraph(markup(c), paragraph_style(size - 1, color)).wrap(width * (0.31 if j == 0 else 0.65) - 18, 1000)[1] for j, c in enumerate(row)) + 13) for row in rows) + 4
    para = Paragraph(markup(str(value)), paragraph_style(size, color))
    return para.wrap(width, 1000)[1] + (10 if kind == "step" else 14)


def fit_size(blocks: list[tuple[str, object]], width: float, height: float, ink: colors.Color, has_image: bool) -> float:
    candidates = [17, 16, 15, 14, 13, 12] if has_image else [20, 19, 18, 17, 16, 15]
    for size in candidates:
        if sum(block_height(b, width, size, ink) for b in blocks) <= height:
            return size
    raise ValueError("Text exceeds slide area even at minimum font size")


def draw_blocks(pdf: canvas.Canvas, blocks: list[tuple[str, object]], x: float, top: float, width: float, size: float, ink: colors.Color) -> float:
    y = top
    for kind, value in blocks:
        if kind == "table":
            for row_index, row in enumerate(value):
                cell_widths = [width * 0.31, width * 0.69]
                cell_paras = [Paragraph(markup(cell), paragraph_style(size - 1, ink, bold=row_index == 0)) for cell in row]
                heights = [p.wrap(cell_widths[j] - 18, 1000)[1] for j, p in enumerate(cell_paras)]
                row_h = max(30, max(heights) + 13)
                pdf.setFillColor(colors.HexColor("#2B78AE") if row_index % 2 == 0 else colors.HexColor("#246DA5"))
                pdf.roundRect(x, y - row_h, width, row_h - 2, 5, fill=1, stroke=0)
                xx = x
                for j, para in enumerate(cell_paras):
                    para.drawOn(pdf, xx + 9, y - heights[j] - 6)
                    xx += cell_widths[j]
                y -= row_h
            y -= 6
            continue
        para = Paragraph(markup(str(value)), paragraph_style(size, ink))
        _, h = para.wrap(width, 1000)
        para.drawOn(pdf, x, y - h)
        y -= h + (10 if kind == "step" else 14)
    return y


def draw_placeholder(pdf: canvas.Canvas, items: list[tuple[str, str]], x: float, y: float, width: float, height: float) -> None:
    pdf.setFillColor(WHITE)
    pdf.roundRect(x, y, width, height, 23, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#8AB8D6"))
    pdf.setLineWidth(1.5)
    pdf.setDash(7, 6)
    pdf.roundRect(x + 11, y + 11, width - 22, height - 22, 17, fill=0, stroke=1)
    pdf.setDash()
    pdf.setFillColor(BLUE)
    pdf.setFont("DejaVu-Bold", 11)
    pdf.drawString(x + 27, y + height - 34, "BILDMATERIAL FOLGT")
    count = len(items)
    usable_top = y + height - 65
    segment_h = (height - 100) / count
    for j, (code, description) in enumerate(items):
        top = usable_top - j * segment_h
        if j:
            pdf.setStrokeColor(colors.HexColor("#D3E5F0"))
            pdf.line(x + 27, top + 9, x + width - 27, top + 9)
        pdf.setFillColor(PALE)
        pdf.roundRect(x + 27, top - 29, 76, 27, 10, fill=1, stroke=0)
        pdf.setFillColor(BLUE)
        pdf.setFont("DejaVu-Bold", 11)
        pdf.drawCentredString(x + 65, top - 20, code)
        para = Paragraph(html.escape(description), paragraph_style(13, INK))
        _, h = para.wrap(width - 145, 1000)
        para.drawOn(pdf, x + 114, top - 3 - h)


def capture(prefix: str, index: int = 0) -> Path | None:
    files = sorted(SCREENSHOTS.glob(f"{prefix}-*.png"))
    if prefix == "S16":
        files = [path for path in files if path.name.endswith("-de.png")]
    return files[index] if len(files) > index else None


def draw_capture(pdf: canvas.Canvas, prefix: str, crop: tuple[int, int, int, int] | None, x: float, y: float, width: float, height: float, index: int = 0) -> None:
    path = capture(prefix, index)
    if path is None:
        raise FileNotFoundError(prefix)
    with Image.open(path) as source:
        img = source.convert("RGB")
        if crop is not None:
            img = img.crop(crop)
        iw, ih = img.size
        scale = min(width / iw, height / ih)
        dw, dh = iw * scale, ih * scale
        pdf.setFillColor(colors.HexColor("#F6FAFC"))
        pdf.roundRect(x, y, width, height, 7, fill=1, stroke=0)
        pdf.drawImage(ImageReader(img), x + (width - dw) / 2, y + (height - dh) / 2, dw, dh)
        pdf.setStrokeColor(colors.HexColor("#CEE2EF"))
        pdf.setLineWidth(0.8)
        pdf.roundRect(x, y, width, height, 7, fill=0, stroke=1)


def draw_onboarding_images(pdf: canvas.Canvas, number: int) -> bool:
    """Use the supplied first-access screenshots; other pages keep placeholders."""
    needed = ["P00", "P01", "P02"] if number == 4 else ["P03", "S01", "S02"]
    if any(capture(prefix) is None for prefix in needed):
        return False
    x, y, w, h = 431, 107, 355, 351
    pdf.setFillColor(WHITE)
    pdf.roundRect(x, y, w, h, 18, fill=1, stroke=0)
    pdf.setFillColor(BLUE)
    pdf.setFont("DejaVu-Bold", 10)
    pdf.drawString(x + 15, y + h - 24, "ERSTZUGANG · AUFNAHMEN")
    if number == 4:
        draw_capture(pdf, "P00", None, x + 14, y + 187, w - 28, 126)
        draw_capture(pdf, "P01", (225, 225, 620, 465), x + 14, y + 16, 156, 147)
        draw_capture(pdf, "P02", (225, 225, 620, 620), x + 185, y + 16, 156, 147)
    else:
        draw_capture(pdf, "P03", (225, 225, 620, 580), x + 14, y + 170, w - 28, 143)
        draw_capture(pdf, "S01", (100, 330, 730, 710), x + 14, y + 16, 156, 130)
        draw_capture(pdf, "S02", (120, 220, 730, 610), x + 185, y + 16, 156, 130)
    return True


def draw_media_gallery(pdf: canvas.Canvas, number: int, x: float, y: float, width: float, height: float) -> bool:
    """Place available screenshots in the image card, with honest missing-asset tiles."""
    items = MEDIA.get(number)
    if not items:
        return False
    pdf.setFillColor(WHITE)
    pdf.roundRect(x, y, width, height, 18, fill=1, stroke=0)
    inset, gap, top = 14, 10, 35
    usable_w = width - 2 * inset
    usable_h = height - top - 15
    count = len(items)
    if count == 1:
        boxes = [(x + inset, y + 15, usable_w, usable_h)]
    elif count == 2:
        tile_w = (usable_w - gap) / 2
        boxes = [(x + inset + i * (tile_w + gap), y + 15, tile_w, usable_h) for i in range(2)]
    else:
        tile_w = (usable_w - gap) / 2
        tile_h = (usable_h - gap) / 2
        boxes = [
            (x + inset + (i % 2) * (tile_w + gap), y + 15 + (1 - i // 2) * (tile_h + gap), tile_w, tile_h)
            for i in range(count)
        ]
    pdf.setFillColor(BLUE)
    pdf.setFont("DejaVu-Bold", 10)
    pdf.drawString(x + inset, y + height - 24, "KASSEL DIALOG · AUFNAHMEN")
    for (code, caption, prefix, index), (bx, by, bw, bh) in zip(items, boxes):
        label_h = 22 if count < 3 else 28
        if prefix and capture(prefix, index):
            draw_capture(pdf, prefix, None, bx, by + label_h, bw, bh - label_h, index)
        else:
            pdf.setFillColor(PALE)
            pdf.roundRect(bx, by + label_h, bw, bh - label_h, 7, fill=1, stroke=0)
            pdf.setStrokeColor(colors.HexColor("#8AB8D6"))
            pdf.setDash(4, 4)
            pdf.roundRect(bx, by + label_h, bw, bh - label_h, 7, fill=0, stroke=1)
            pdf.setDash()
            pdf.setFillColor(BLUE)
            pdf.setFont("DejaVu-Bold", 13)
            pdf.drawCentredString(bx + bw / 2, by + label_h + (bh - label_h) / 2, code)
        label = Paragraph(html.escape(caption), paragraph_style(8.5, INK))
        _, lh = label.wrap(bw, label_h)
        label.drawOn(pdf, bx, by + label_h - lh - 1)
    return True


def draw_header(pdf: canvas.Canvas, title: str, number: int) -> None:
    pdf.setFillColor(BLUE)
    pdf.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    pdf.setFillColor(CYAN)
    pdf.rect(0, PAGE_H - 11, PAGE_W, 11, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("DejaVu", 11)
    pdf.drawRightString(PAGE_W - 51, PAGE_H - 43, "KasselDIALOG")
    title_size = 27
    while pdfmetrics.stringWidth(title, "DejaVu-Bold", title_size) > PAGE_W - 140:
        title_size -= 1
    pdf.setFont("DejaVu-Bold", title_size)
    pdf.drawString(55, PAGE_H - 88, title)
    pdf.setStrokeColor(CYAN)
    pdf.setLineWidth(2)
    pdf.line(55, PAGE_H - 106, PAGE_W - 55, PAGE_H - 106)
    pdf.setFillColor(colors.HexColor("#D7EAF6"))
    pdf.setFont("DejaVu", 9)
    pdf.drawString(55, 30, "KasselDIALOG · Nutzerdokumentation · Arbeitsfassung")
    pdf.drawRightString(PAGE_W - 55, 30, f"{number:02d} / 26")


def draw_title_page(pdf: canvas.Canvas, title: str, blocks: list[tuple[str, object]]) -> None:
    pdf.setFillColor(WHITE)
    pdf.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    pdf.setFillColor(BLUE)
    pdf.roundRect(57, PAGE_H - 86, 185, 32, 16, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("DejaVu-Bold", 12)
    pdf.drawCentredString(149, PAGE_H - 75, "KasselDIALOG")
    pdf.setFillColor(INK)
    pdf.setFont("DejaVu-Bold", 33)
    pdf.drawString(57, PAGE_H - 183, "KasselDIALOG")
    pdf.setFillColor(BLUE)
    pdf.setFont("DejaVu", 24)
    pdf.drawString(57, PAGE_H - 220, "Nutzerdokumentation")
    draw_blocks(pdf, blocks, 58, PAGE_H - 260, 345, 16, INK)
    if not draw_media_gallery(pdf, 1, 443, 113, 342, 338):
        draw_placeholder(pdf, PLACEHOLDERS[1], 443, 113, 342, 338)
    pdf.setFillColor(colors.HexColor("#637A89"))
    pdf.setFont("DejaVu", 10)
    pdf.drawString(57, 48, "Arbeitsfassung · einzelne Bilder und Datenschutzfreigabe ausstehend")


def build() -> None:
    setup_fonts()
    paths = sorted(PAGES.glob("[0-9][0-9]-*.md"))
    if len(paths) != 26:
        raise ValueError(f"Expected 26 slide files, found {len(paths)}")
    pdf = canvas.Canvas(str(OUTPUT), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    pdf.setTitle("KasselDIALOG – Nutzerdokumentation (Arbeitsfassung)")
    pdf.setAuthor("KasselDIALOG")
    pdf.setSubject("A4-Querformat mit Screenshots und Platzhaltern für fehlende Grafiken")
    for number, path in enumerate(paths, start=1):
        title, blocks = parse_page(path)
        if number == 1:
            draw_title_page(pdf, title, blocks)
        else:
            draw_header(pdf, title, number)
            placeholders = PLACEHOLDERS.get(number)
            if placeholders:
                text_x, text_width = 58, 347
                size = fit_size(blocks, text_width, 382, WHITE, True)
                bottom = draw_blocks(pdf, blocks, text_x, PAGE_H - 133, text_width, size, WHITE)
                if bottom < 61:
                    raise ValueError(f"Text clips on slide {number}: y={bottom:.1f}")
                if number in (4, 5) and draw_onboarding_images(pdf, number):
                    pass
                elif draw_graphic(pdf, number, 431, 107, 355, 351):
                    pass
                elif draw_media_gallery(pdf, number, 431, 107, 355, 351):
                    pass
                else:
                    draw_placeholder(pdf, placeholders, 431, 107, 355, 351)
            else:
                pdf.setFillColor(colors.HexColor("#246FA8"))
                pdf.roundRect(55, 100, PAGE_W - 110, 355, 18, fill=1, stroke=0)
                text_x, text_width = 80, PAGE_W - 160
                size = fit_size(blocks, text_width, 310, WHITE, False)
                bottom = draw_blocks(pdf, blocks, text_x, PAGE_H - 154, text_width, size, WHITE)
                if bottom < 112:
                    raise ValueError(f"Text clips on slide {number}: y={bottom:.1f}")
        pdf.showPage()
    pdf.save()
    print(f"Created {OUTPUT} ({len(paths)} A4 landscape pages)")


if __name__ == "__main__":
    build()
