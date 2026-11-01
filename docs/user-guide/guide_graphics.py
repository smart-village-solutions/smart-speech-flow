"""Vector artwork for the KasselDIALOG operator guide.

The three illustrations use the same 355 × 351 point drawing area as the
image cards in the A4 landscape guide. ``draw_graphic`` scales them to any
target rectangle, including standalone PDF exports.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas


BLUE = colors.HexColor("#1D639D")
DEEP = colors.HexColor("#103F67")
CYAN = colors.HexColor("#73D8E5")
PALE = colors.HexColor("#EAF5FA")
GREEN = colors.HexColor("#6CBFA8")
INK = colors.HexColor("#183247")
MUTED = colors.HexColor("#567488")
WHITE = colors.white


def _card(pdf: Canvas, title: str) -> None:
    pdf.setFillColor(WHITE)
    pdf.roundRect(0, 0, 355, 351, 18, fill=1, stroke=0)
    pdf.setFillColor(BLUE)
    pdf.setFont("DejaVu-Bold", 10)
    pdf.drawString(16, 326, title)


def _text(pdf: Canvas, x: float, y: float, value: str, size: float = 11, *, bold: bool = False, color=INK) -> None:
    pdf.setFillColor(color)
    pdf.setFont("DejaVu-Bold" if bold else "DejaVu", size)
    pdf.drawCentredString(x, y, value)


def _arrow(pdf: Canvas, x1: float, y1: float, x2: float, y2: float, color=BLUE, width: float = 3) -> None:
    pdf.setStrokeColor(color)
    pdf.setFillColor(color)
    pdf.setLineWidth(width)
    pdf.line(x1, y1, x2, y2)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        arrow = [(x2, y2), (x2 - direction * 8, y2 + 5), (x2 - direction * 8, y2 - 5)]
    else:
        direction = 1 if y2 > y1 else -1
        arrow = [(x2, y2), (x2 - 5, y2 - direction * 8), (x2 + 5, y2 - direction * 8)]
    path = pdf.beginPath()
    path.moveTo(*arrow[0])
    for point in arrow[1:]:
        path.lineTo(*point)
    path.close()
    pdf.drawPath(path, fill=1, stroke=0)


def _person(pdf: Canvas, x: float, y: float, color) -> None:
    pdf.setFillColor(color)
    pdf.circle(x, y + 23, 14, fill=1, stroke=0)
    pdf.roundRect(x - 26, y - 22, 52, 34, 14, fill=1, stroke=0)


def _g02(pdf: Canvas) -> None:
    _card(pdf, "GESPRÄCH IN ZWEI SPRACHEN")
    pdf.setFillColor(PALE)
    pdf.roundRect(18, 171, 107, 123, 13, fill=1, stroke=0)
    pdf.roundRect(230, 171, 107, 123, 13, fill=1, stroke=0)
    _person(pdf, 71, 238, BLUE)
    _person(pdf, 284, 238, GREEN)
    _text(pdf, 71, 186, "Mitarbeitende", 10, bold=True)
    _text(pdf, 284, 186, "Gast", 10, bold=True)
    pdf.setFillColor(BLUE)
    pdf.circle(177.5, 230, 39, fill=1, stroke=0)
    _text(pdf, 177.5, 234, "Kassel", 10, bold=True, color=WHITE)
    _text(pdf, 177.5, 218, "DIALOG", 10, bold=True, color=WHITE)
    _arrow(pdf, 126, 248, 135, 248, CYAN)
    _arrow(pdf, 220, 212, 229, 212, GREEN)
    pdf.setFillColor(PALE)
    pdf.roundRect(27, 88, 301, 56, 12, fill=1, stroke=0)
    _arrow(pdf, 86, 116, 267, 116, BLUE, 2)
    _arrow(pdf, 269, 102, 88, 102, GREEN, 2)
    _text(pdf, 177.5, 62, "Nachrichten werden in beide Richtungen übertragen", 9.2, color=MUTED)


def _icon_check(pdf: Canvas, x: float, y: float) -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(3)
    pdf.roundRect(x - 17, y - 17, 34, 34, 5, fill=0, stroke=1)
    pdf.line(x - 9, y, x - 2, y - 7)
    pdf.line(x - 2, y - 7, x + 11, y + 9)


def _icon_tech(pdf: Canvas, x: float, y: float) -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(3)
    pdf.roundRect(x - 17, y - 13, 34, 25, 3, fill=0, stroke=1)
    pdf.line(x - 22, y - 19, x + 22, y - 19)
    pdf.setFillColor(BLUE)
    pdf.circle(x, y - 3, 3, fill=1, stroke=0)


def _icon_privacy(pdf: Canvas, x: float, y: float) -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(3)
    pdf.roundRect(x - 16, y - 15, 32, 25, 4, fill=0, stroke=1)
    pdf.arc(x - 11, y - 1, x + 11, y + 22, startAng=0, extent=180)
    pdf.setFillColor(BLUE)
    pdf.circle(x, y - 4, 3, fill=1, stroke=0)


def _icon_clarify(pdf: Canvas, x: float, y: float) -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(3)
    pdf.circle(x, y + 12, 9, fill=0, stroke=1)
    pdf.arc(x - 20, y - 27, x + 20, y + 2, startAng=0, extent=180)
    pdf.line(x + 11, y - 7, x + 16, y - 12)
    pdf.line(x + 16, y - 12, x + 25, y - 1)


def _g03(pdf: Canvas) -> None:
    _card(pdf, "VOR DEM GESPRÄCH PRÜFEN")
    cells = [
        (18, 173, "01", "Freigabe", "Einsatzrahmen", _icon_check),
        (183, 173, "02", "Technik", "Gerät und Verbindung", _icon_tech),
        (18, 35, "03", "Datenschutz", "Information verfügbar", _icon_privacy),
        (183, 35, "04", "Klärung", "Wichtige Aussagen", _icon_clarify),
    ]
    for x, y, number, name, detail, icon in cells:
        pdf.setFillColor(PALE)
        pdf.roundRect(x, y, 154, 128, 12, fill=1, stroke=0)
        pdf.setFillColor(CYAN)
        pdf.circle(x + 23, y + 103, 13, fill=1, stroke=0)
        _text(pdf, x + 23, y + 99, number, 8, bold=True, color=DEEP)
        icon(pdf, x + 77, y + 78)
        _text(pdf, x + 77, y + 37, name, 11, bold=True)
        _text(pdf, x + 77, y + 18, detail, 8, color=MUTED)


def _step_icon(pdf: Canvas, kind: str, x: float, y: float) -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(2)
    if kind == "wave":
        for dx, length in [(-12, 11), (-6, 22), (0, 29), (6, 17), (12, 10)]:
            pdf.line(x + dx, y - length / 2, x + dx, y + length / 2)
    elif kind == "text":
        for dy, length in [(9, 23), (2, 23), (-5, 16)]:
            pdf.line(x - 12, y + dy, x - 12 + length, y + dy)
    elif kind == "translate":
        _arrow(pdf, x - 13, y + 5, x + 12, y + 5, BLUE, 2)
        _arrow(pdf, x + 13, y - 6, x - 12, y - 6, GREEN, 2)
    else:
        pdf.roundRect(x - 14, y - 9, 28, 20, 5, fill=0, stroke=1)
        pdf.line(x - 5, y - 9, x - 9, y - 14)


def _g04(pdf: Canvas) -> None:
    _card(pdf, "VON DER SPRACHE ZUR NACHRICHT")
    steps = [
        (256, "01", "Sprache", "wave"),
        (194, "02", "Erkannter Text", "text"),
        (132, "03", "Übersetzung", "translate"),
        (70, "04", "Nachricht / Sprachausgabe", "message"),
    ]
    for y, number, title, icon in steps:
        pdf.setFillColor(PALE)
        pdf.roundRect(25, y, 305, 51, 12, fill=1, stroke=0)
        pdf.setFillColor(CYAN)
        pdf.circle(50, y + 25, 14, fill=1, stroke=0)
        _text(pdf, 50, y + 21, number, 8, bold=True, color=DEEP)
        _step_icon(pdf, icon, 91, y + 25)
        pdf.setFillColor(INK)
        pdf.setFont("DejaVu-Bold", 10 if len(title) > 22 else 12)
        pdf.drawString(120, y + 20, title)
        if y > 70:
            _arrow(pdf, 177.5, y - 2, 177.5, y - 10, CYAN, 2)
    _text(pdf, 177.5, 40, "Lokal betriebene KI-Modelle", 9, bold=True, color=DEEP)
    _text(pdf, 177.5, 23, "Wichtige Aussagen menschlich prüfen", 8, color=MUTED)


GRAPHICS = {2: _g02, 3: _g03, 17: _g04}


def draw_graphic(pdf: Canvas, number: int, x: float, y: float, width: float, height: float) -> bool:
    graphic = GRAPHICS.get(number)
    if graphic is None:
        return False
    pdf.saveState()
    pdf.translate(x, y)
    pdf.scale(width / 355, height / 351)
    graphic(pdf)
    pdf.restoreState()
    return True
