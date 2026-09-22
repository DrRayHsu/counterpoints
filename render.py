"""Draws the two-quote card."""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, MARGIN = 1600, 130
BG, FG, MUTED, RULE = (250, 248, 243), (28, 26, 23), (110, 104, 96), (200, 194, 184)
F = Path(__file__).parent
font_q = ImageFont.truetype(str(F / "EBGaramond-400-normal.ttf"), 50)
font_a = ImageFont.truetype(str(F / "EBGaramond-400-italic.ttf"), 34)
font_t = ImageFont.truetype(str(F / "EBGaramond-500-normal.ttf"), 28)


def _wrap(text, font, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= width:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def attribution_line(q):
    line = "— " + q["attribution"]
    if q.get("found_by"):
        line += f" · found by @{q['found_by']['handle']}"
    return line


def card(a, b):
    """Returns (png_bytes, (width, height))."""
    width = W - 2 * MARGIN
    blocks = [(_wrap("“" + q["text"] + "”", font_q, width),
               _wrap(attribution_line(q), font_a, width)) for q in (a, b)]
    lh_q, lh_a, gap = 66, 46, 110
    h = MARGIN + sum(len(ql) * lh_q + 24 + len(al) * lh_a for ql, al in blocks) + gap + MARGIN + 30
    h = max(h, 900)

    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)
    y = MARGIN
    for i, (ql, al) in enumerate(blocks):
        for line in ql:
            d.text((MARGIN, y), line, font=font_q, fill=FG)
            y += lh_q
        y += 24
        for line in al:
            d.text((MARGIN, y), line, font=font_a, fill=MUTED)
            y += lh_a
        if i == 0:
            mid = y + gap // 2
            d.line([(MARGIN, mid), (MARGIN + 160, mid)], fill=RULE, width=2)
            y += gap
    d.text((MARGIN, h - MARGIN + 40), "COUNTERPOINTS", font=font_t, fill=RULE)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), (W, h)


def alt_text(a, b):
    return "\n\n".join(f"“{q['text']}” {attribution_line(q)}" for q in (a, b))[:2000]
