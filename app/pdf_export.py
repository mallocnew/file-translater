from __future__ import annotations

import io
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.docx_export import parse_markdown

_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
_FONT = "LayoutSans"
_FONT_BOLD = "LayoutSans-Bold"
_MONO = "LayoutMono"
_registered = False


def markdown_to_pdf(markdown: str) -> bytes:
    _ensure_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="translation",
    )
    styles = _styles()
    story: list = []
    for block in parse_markdown(markdown):
        kind = block["type"]
        if kind == "heading":
            style = styles[f"h{block['level']}"]
            story.append(Paragraph(_markup(block["text"]), style))
            story.append(Spacer(1, 4 * mm))
        elif kind == "paragraph":
            story.append(Paragraph(_markup(block["text"]), styles["body"]))
            story.append(Spacer(1, 3 * mm))
        elif kind == "quote":
            story.append(Paragraph(_markup(block["text"]), styles["quote"]))
            story.append(Spacer(1, 3 * mm))
        elif kind in {"ul", "ol"}:
            items = [
                ListItem(Paragraph(_markup(item), styles["body"]), leftIndent=8)
                for item in block["items"]
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="1" if kind == "ol" else "bullet",
                    start="1",
                    leftIndent=12,
                    bulletFontName=_FONT,
                    bulletFontSize=11,
                )
            )
            story.append(Spacer(1, 3 * mm))
        elif kind == "code":
            story.append(Preformatted(block["text"] or " ", styles["code"]))
            story.append(Spacer(1, 3 * mm))
        elif kind == "table":
            rows = block["rows"]
            data = [[Paragraph(_markup(cell), styles["cell"]) for cell in row] for row in rows]
            table = Table(data, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), _FONT),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f1e6")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9cbb3")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 4 * mm))
    if not story:
        story.append(Paragraph(" ", styles["body"]))
    document.build(story)
    return buffer.getvalue()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles = {
        "body": ParagraphStyle(
            "LayoutBody",
            parent=base["BodyText"],
            fontName=_FONT,
            fontSize=11,
            leading=18,
            textColor=colors.HexColor("#1c1915"),
            alignment=TA_JUSTIFY,
            spaceAfter=0,
        ),
        "quote": ParagraphStyle(
            "LayoutQuote",
            parent=base["BodyText"],
            fontName=_FONT,
            fontSize=11,
            leading=18,
            textColor=colors.HexColor("#6f675c"),
            leftIndent=10,
            borderPadding=4,
            alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "LayoutCell",
            parent=base["BodyText"],
            fontName=_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#1c1915"),
        ),
        "code": ParagraphStyle(
            "LayoutCode",
            parent=base["Code"],
            fontName=_MONO,
            fontSize=9,
            leading=13,
            backColor=colors.HexColor("#f6f0e6"),
            leftIndent=8,
            rightIndent=8,
        ),
    }
    for level, size, leading in ((1, 20, 26), (2, 16, 22), (3, 13, 18), (4, 12, 16)):
        styles[f"h{level}"] = ParagraphStyle(
            f"LayoutH{level}",
            parent=base["Heading1"],
            fontName=_FONT_BOLD,
            fontSize=size,
            leading=leading,
            textColor=colors.HexColor("#1c1915"),
            spaceBefore=0,
            spaceAfter=0,
        )
    return styles


def _markup(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    pieces: list[str] = []
    position = 0
    for match in _INLINE.finditer(escaped):
        pieces.append(escaped[position : match.start()])
        token = match.group(0)
        if token.startswith("**"):
            pieces.append(f"<b>{token[2:-2]}</b>")
        else:
            pieces.append(f"<font face='{_MONO}'>{token[1:-1]}</font>")
        position = match.end()
    pieces.append(escaped[position:])
    return "".join(pieces) or " "


def _ensure_fonts() -> None:
    global _registered, _FONT, _FONT_BOLD, _MONO
    if _registered:
        return
    regular, bold = _system_font_pair()
    if regular:
        pdfmetrics.registerFont(TTFont(_FONT, str(regular[0]), subfontIndex=regular[1]))
        if bold:
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold[0]), subfontIndex=bold[1]))
        else:
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(regular[0]), subfontIndex=regular[1]))
        mono = _mono_font()
        if mono:
            pdfmetrics.registerFont(TTFont(_MONO, str(mono[0]), subfontIndex=mono[1]))
        else:
            pdfmetrics.registerFont(TTFont(_MONO, str(regular[0]), subfontIndex=regular[1]))
    else:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONT = "STSong-Light"
        _FONT_BOLD = "STSong-Light"
        _MONO = "STSong-Light"
    _registered = True


def _system_font_pair() -> tuple[tuple[Path, int] | None, tuple[Path, int] | None]:
    regular = _first_font(
        [
            (Path(r"C:\Windows\Fonts\msyh.ttc"), 0),
            (Path(r"C:\Windows\Fonts\simhei.ttf"), 0),
            (Path(r"C:\Windows\Fonts\simsun.ttc"), 0),
            (Path("/System/Library/Fonts/STHeiti Light.ttc"), 0),
            (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
            (Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"), 0),
        ]
    )
    bold = _first_font(
        [
            (Path(r"C:\Windows\Fonts\msyhbd.ttc"), 0),
            (Path(r"C:\Windows\Fonts\simhei.ttf"), 0),
            (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 0),
        ]
    )
    return regular, bold


def _mono_font() -> tuple[Path, int] | None:
    return _first_font(
        [
            (Path(r"C:\Windows\Fonts\consola.ttf"), 0),
            (Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"), 0),
        ]
    )


def _first_font(candidates: list[tuple[Path, int]]) -> tuple[Path, int] | None:
    for path, index in candidates:
        if path.is_file():
            return path, index
    return None
