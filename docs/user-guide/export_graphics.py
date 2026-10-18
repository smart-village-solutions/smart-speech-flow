#!/usr/bin/env python3
"""Export the guide's vector illustrations as standalone PDF and SVG files.

Requires ReportLab and PyMuPDF. Run: python docs/user-guide/export_graphics.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from reportlab.pdfgen import canvas

from build_pdf import setup_fonts
from guide_graphics import draw_graphic


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "graphics"


def main() -> None:
    setup_fonts()
    OUTPUT.mkdir(exist_ok=True)
    for number in (2, 3, 17):
        code = {2: "G02", 3: "G03", 17: "G04"}[number]
        pdf_path = OUTPUT / f"{code}.pdf"
        pdf = canvas.Canvas(str(pdf_path), pagesize=(355, 351))
        draw_graphic(pdf, number, 0, 0, 355, 351)
        pdf.showPage()
        pdf.save()
        with pymupdf.open(pdf_path) as document:
            (OUTPUT / f"{code}.svg").write_text(document[0].get_svg_image(), encoding="utf-8")
        print(f"Created {pdf_path} and {code}.svg")


if __name__ == "__main__":
    main()
