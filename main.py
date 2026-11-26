#!/usr/bin/env python3
"""One image that sums up the world news of Wednesday 25 November 2026.

The program is self-contained: it uses only the Python standard library,
reads a bitmap font pack (fonts.bin, produced by extract_fonts.py) from
its own directory, paints six news cards onto an in-memory RGB canvas
and stores the result as entry.png inside $MAKEFUN_OUTPUT_DIR (falling
back to /output).  No network, no randomness: two runs agree byte for
byte.

Every story below was checked against wire reporting dated 25 November
2026 (Reuters and SCMP): each item happened, or was first reported, on
that day.
"""

import math
import os
import struct
import zlib

SIZE = 1024

# Colours used across the page (RGB tuples).
PAPER = (250, 246, 238)
BLACK = (22, 22, 22)
GREY = (96, 92, 84)
BODY = (58, 58, 58)
NAVY = (27, 58, 92)
RED = (179, 38, 30)
WHITE = (255, 255, 255)
CARD_BG = (255, 255, 255)
CARD_EDGE = (216, 210, 196)
GOLD = (176, 124, 0)
TEAL = (0, 110, 110)
GREEN = (46, 125, 50)
PLUM = (103, 58, 140)

# One entry per story: section label, accent colour, headline, summary,
# wire credit and the name of the pictogram drawn in the corner.
STORIES = [
    ("TRADE \u00b7 US", RED,
     "US unveils new tariffs of up to 20%",
     "Washington proposes tariffs of up to 20% on China, the EU and 12 "
     "other nations after an eight-month excess-capacity probe.",
     "REUTERS", "chart"),
    ("SPACE \u00b7 CHINA", NAVY,
     "Shenzhou-24 docks at space station",
     "Shenzhou-24 docks at the Tiangong station, carrying Pakistani "
     "pilot Muhammad Zeeshan Ali, a first foreign astronaut.",
     "SCMP", "globe"),
    ("COURTS \u00b7 US", PLUM,
     "US jury convicts Huawei of fraud",
     "A federal jury finds Huawei guilty of fraud and conspiring to "
     "steal trade secrets in the long-running Iran sanctions case.",
     "REUTERS", "burst"),
    ("CONFLICT \u00b7 GULF", GOLD,
     "Houthis hit Riyadh\u2019s tallest tower",
     "A Houthi strike hits Riyadh\u2019s tallest tower again, wounding "
     "11 people, in a fresh escalation across the Gulf.",
     "REUTERS", "flame"),
    ("CRIME \u00b7 LATIN AMERICA", TEAL,
     "Hostages freed in Colombia raid",
     "Police free hostages held in a Cartagena supermarket after a "
     "failed armoured-car raid; one captor is killed.",
     "REUTERS", "globe"),
    ("LABOUR \u00b7 SOUTH ASIA", GREEN,
     "Bangladesh raises garment wage 36%",
     "Bangladesh lifts garment workers\u2019 minimum wage 36% to $139 "
     "a month after weeks of protests.",
     "SCMP", "chart"),
]

DATELINE = "WEDNESDAY 25 NOVEMBER 2026"
TITLE = "THE WORLD IN A DAY"
COLOPHON = ("SOURCES: REUTERS \u00b7 SCMP"
            "  \u2014  SIX STORIES THAT DEFINED THE DAY")


# ---------------------------------------------------------------- fonts
class Reader:
    """A little cursor over the font pack bytes."""

    def __init__(self, blob):
        self.blob = blob
        self.pos = 0

    def take(self, n):
        piece = self.blob[self.pos:self.pos + n]
        self.pos += n
        return piece

    def u8(self):
        value = self.blob[self.pos]
        self.pos += 1
        return value

    def u32(self):
        value = struct.unpack_from("<I", self.blob, self.pos)[0]
        self.pos += 4
        return value


def load_fonts(blob):
    """Parse the FNT1 pack into {name: (pixel size, {codepoint: glyph})}."""
    rdr = Reader(blob)
    if rdr.take(4) != b"FNT1":
        raise ValueError("fonts.bin is not an FNT1 pack")
    fonts = {}
    for _ in range(rdr.u32()):
        name = rdr.take(rdr.u8()).decode("ascii")
        size = rdr.u32()
        glyphs = {}
        for _ in range(rdr.u32()):
            cp, bx, bt, w, h, adv = struct.unpack_from(
                "<IhhHHH", rdr.blob, rdr.pos)
            rdr.pos += 14
            glyphs[cp] = (bx, bt, w, h, adv, rdr.take(w * h))
        fonts[name] = (size, glyphs)
    return fonts


class Typesetter:
    """Measures and wraps strings against one font pack."""

    def __init__(self, fonts):
        self.fonts = fonts

    def advance(self, style, text):
        glyphs = self.fonts[style][1]
        fallback = glyphs[ord("?")]
        return sum(glyphs.get(ord(ch), fallback)[4] for ch in text)

    def wrap(self, style, text, limit):
        """Split text into lines no wider than limit pixels."""
        lines = []
        current = ""
        for word in text.split(" "):
            trial = word if not current else current + " " + word
            if self.advance(style, trial) <= limit:
                current = trial
                continue
            if current:
                lines.append(current)
            # A single word wider than the line is cut at the last
            # character that still fits, and wrapping continues.
            while self.advance(style, word) > limit and len(word) > 1:
                cut = 1
                while (cut < len(word)
                       and self.advance(style, word[:cut + 1]) <= limit):
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
        return lines


# --------------------------------------------------------------- canvas
class Page:
    """An RGB framebuffer with the drawing primitives the layout needs."""

    def __init__(self, width, height, colour):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 3)
        r, g, b = colour
        for i in range(0, len(self.pixels), 3):
            self.pixels[i] = r
            self.pixels[i + 1] = g
            self.pixels[i + 2] = b

    def _offset(self, x, y):
        return (y * self.width + x) * 3

    def paint(self, x, y, colour, alpha=255):
        """Set one pixel, blending by alpha (0..255) when below opaque."""
        if not (0 <= x < self.width and 0 <= y < self.height) or alpha <= 0:
            return
        i = self._offset(x, y)
        if alpha >= 255:
            self.pixels[i], self.pixels[i + 1], self.pixels[i + 2] = colour
            return
        keep = 255 - alpha
        self.pixels[i] = (colour[0] * alpha + self.pixels[i] * keep) // 255
        self.pixels[i + 1] = (colour[1] * alpha
                             + self.pixels[i + 1] * keep) // 255
        self.pixels[i + 2] = (colour[2] * alpha
                             + self.pixels[i + 2] * keep) // 255

    def rect(self, x, y, w, h, colour):
        """Fill the rectangle clipped to the page."""
        left = max(0, x)
        top = max(0, y)
        right = min(self.width, x + w)
        bottom = min(self.height, y + h)
        r, g, b = colour
        for yy in range(top, bottom):
            base = (yy * self.width + left) * 3
            for xx in range(left, right):
                i = base + (xx - left) * 3
                self.pixels[i] = r
                self.pixels[i + 1] = g
                self.pixels[i + 2] = b

    def disc(self, cx, cy, radius, colour):
        for dy in range(-radius, radius + 1):
            half = int((radius * radius - dy * dy) ** 0.5)
            self.rect(cx - half, cy + dy, half * 2 + 1, 1, colour)

    def ring(self, cx, cy, radius, thickness, colour, inside):
        self.disc(cx, cy, radius, colour)
        self.disc(cx, cy, radius - thickness, inside)

    def stroke(self, x0, y0, x1, y1, colour, width=1):
        """A line drawn as a row of small discs along its length."""
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            t = s / steps
            self.disc(int(round(x0 + (x1 - x0) * t)),
                      int(round(y0 + (y1 - y0) * t)), width // 2, colour)

    def polygon(self, points, colour):
        """Scanline fill using the non-zero winding rule."""
        if len(points) < 3:
            return
        edges = []
        count = len(points)
        for i in range(count):
            x0, y0 = points[i]
            x1, y1 = points[(i + 1) % count]
            if y0 == y1:
                continue
            direction = 1
            if y0 > y1:
                x0, y0, x1, y1 = x1, y1, x0, y0
                direction = -1
            edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), direction))
        y_lo = max(0, min(p[1] for p in points))
        y_hi = min(self.height - 1, max(p[1] for p in points))
        for y in range(y_lo, y_hi + 1):
            scan = y + 0.5
            crossings = []
            for y0, y1, x0, slope, direction in edges:
                if y0 <= scan < y1:
                    crossings.append((x0 + (scan - y0) * slope, direction))
            crossings.sort()
            winding = 0
            previous = None
            for x, direction in crossings:
                if previous is not None and winding != 0:
                    xa = max(0, int(previous + 0.5))
                    xb = min(self.width, int(x + 0.5))
                    if xb > xa:
                        self.rect(xa, y, xb - xa, 1, colour)
                winding += direction
                previous = x

    def paste(self, other, dx, dy, dw, dh):
        """Copy another page scaled into a dw x dh box (nearest neighbour)."""
        for yy in range(dh):
            sy = min(other.height - 1, yy * other.height // dh)
            for xx in range(dw):
                sx = min(other.width - 1, xx * other.width // dw)
                i = self._offset(dx + xx, dy + yy)
                j = (sy * other.width + sx) * 3
                self.pixels[i] = other.pixels[j]
                self.pixels[i + 1] = other.pixels[j + 1]
                self.pixels[i + 2] = other.pixels[j + 2]

    def text(self, setter, style, x, baseline, string, colour):
        """Draw one string with its baseline at the given y."""
        glyphs = setter.fonts[style][1]
        fallback = glyphs[ord("?")]
        pen = x
        for ch in string:
            bx, bt, w, h, adv, coverage = glyphs.get(ord(ch), fallback)
            for row in range(h):
                yy = baseline - bt + row
                if not 0 <= yy < self.height:
                    continue
                for col in range(w):
                    alpha = coverage[row * w + col]
                    if alpha:
                        self.paint(pen + bx + col, yy, colour, alpha)
            pen += adv
        return pen


# ------------------------------------------------------------- pictograms
def pictogram(page, kind, x, y, box, colour):
    """Draw one small icon inside a box x box square at (x, y)."""
    mid = box // 2
    if kind == "globe":
        page.ring(x + mid, y + mid, mid - 2, 4, colour, CARD_BG)
        page.stroke(x + 8, y + mid, x + box - 8, y + mid, colour, 3)
        page.stroke(x + mid, y + 8, x + mid, y + box - 8, colour, 3)
        page.polygon([(x + box - 22, y + 14), (x + box - 4, y + 6),
                      (x + box - 10, y + 22)], RED)
    elif kind == "pill":
        page.stroke(x + 10, y + box - 12, x + box - 10, y + 12, colour, 20)
    elif kind == "quake":
        page.disc(x + mid, y + mid, 5, colour)
        for radius in (10, 17, 24):
            page.ring(x + mid, y + mid, radius, 3, colour, CARD_BG)
        page.stroke(x + 6, y + box - 6, x + 20, y + box - 20, colour, 4)
        page.stroke(x + 20, y + box - 20, x + 30, y + box - 10, colour, 4)
        page.stroke(x + 30, y + box - 10, x + box - 8, y + box - 24,
                    colour, 4)
    elif kind == "chart":
        page.rect(x + 10, y + box - 24, 10, 14, colour)
        page.rect(x + 26, y + box - 36, 10, 26, colour)
        page.rect(x + 42, y + box - 48, 10, 38, colour)
        page.stroke(x + 8, y + box - 26, x + 28, y + box - 40, RED, 4)
        page.stroke(x + 28, y + box - 40, x + 52, y + box - 52, RED, 4)
        page.polygon([(x + 52, y + box - 52), (x + 40, y + box - 52),
                      (x + 52, y + box - 40)], RED)
    elif kind == "flame":
        page.polygon([
            (x + mid, y + 4), (x + box - 10, y + 26), (x + box - 6, y + 40),
            (x + box - 14, y + box - 8), (x + 14, y + box - 8),
            (x + 10, y + 40), (x + 6, y + 26),
        ], (230, 92, 0))
        page.polygon([
            (x + mid, y + 26), (x + box - 16, y + 40),
            (x + box - 12, y + box - 12), (x + 12, y + box - 12),
            (x + 16, y + 40),
        ], (255, 196, 0))
    elif kind == "burst":
        points = []
        for i in range(16):
            angle = math.pi * i / 8.0
            radius = (mid - 2) if i % 2 == 0 else (box // 5)
            points.append((int(x + mid + radius * math.cos(angle)),
                           int(y + mid + radius * math.sin(angle))))
        page.polygon(points, colour)
        page.disc(x + mid, y + mid, 7, WHITE)


# --------------------------------------------------------------- layout
def draw_story(page, setter, x, y, w, h, story):
    label, accent, headline, summary, credit, icon = story
    pad = 18
    page.rect(x, y, w, h, CARD_BG)
    page.rect(x, y, w, 6, accent)
    page.rect(x, y + h - 1, w, 1, CARD_EDGE)
    page.rect(x, y, 1, h, CARD_EDGE)
    page.rect(x + w - 1, y, 1, h, CARD_EDGE)
    page.rect(x, y, w, 1, CARD_EDGE)
    # Section label, with the pictogram at the right of the same row.
    page.text(setter, "bold16", x + pad, y + 32, label, accent)
    tile = Page(60, 60, CARD_BG)
    pictogram(tile, icon, 0, 0, 60, accent)
    page.paste(tile, x + w - pad - 44, y + 8, 44, 44)
    # Headline: at most two lines, across the full width of the card.
    hy = y + 52
    for line in setter.wrap("bold30", headline, w - pad * 2)[:2]:
        page.text(setter, "bold30", x + pad, hy + 30, line, BLACK)
        hy += 36
    # Summary: at most three lines under the headline.
    sy = y + 52 + 2 * 36 + 8
    for line in setter.wrap("reg20", summary, w - pad * 2)[:3]:
        page.text(setter, "reg20", x + pad, sy + 20, line, BODY)
        sy += 26
    # A rule and the wire credit close the card.
    foot = y + h - 34
    page.rect(x + pad, foot, w - pad * 2, 1, CARD_EDGE)
    page.text(setter, "bold16", x + pad, foot + 24, "SOURCE: " + credit,
              accent)


def render():
    folder = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(folder, "fonts.bin"), "rb") as handle:
        setter = Typesetter(load_fonts(handle.read()))
    page = Page(SIZE, SIZE, PAPER)

    # Masthead and the red dateline strip under it.
    page.rect(0, 0, SIZE, 112, NAVY)
    title_w = setter.advance("bold46", TITLE)
    page.text(setter, "bold46", (SIZE - title_w) // 2, 76, TITLE, WHITE)
    page.rect(0, 112, SIZE, 4, GOLD)
    page.rect(0, 116, SIZE, 44, RED)
    date_w = setter.advance("bold21", DATELINE)
    page.text(setter, "bold21", (SIZE - date_w) // 2, 150, DATELINE, WHITE)

    # Six cards in two columns and three rows.
    margin, gap, top = 24, 18, 172
    card_w = (SIZE - margin * 2 - gap) // 2
    card_h = 261
    # Fail loudly rather than clip: every headline must fit its two
    # lines and every summary its three at the card's text width.
    for story in STORIES:
        assert len(setter.wrap("bold30", story[2], card_w - 36)) <= 2
        assert len(setter.wrap("reg20", story[3], card_w - 36)) <= 3
    for index, story in enumerate(STORIES):
        cx = margin + (index % 2) * (card_w + gap)
        cy = top + (index // 2) * (card_h + gap)
        draw_story(page, setter, cx, cy, card_w, card_h, story)

    # Colophon centred at the foot of the page.
    foot_w = setter.advance("reg14", COLOPHON)
    page.text(setter, "reg14", (SIZE - foot_w) // 2, 1014, COLOPHON, GREY)

    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as handle:
        handle.write(png_bytes(SIZE, SIZE, bytes(page.pixels)))
    return path


def png_bytes(width, height, rgb):
    """Encode 8-bit RGB pixels as a PNG with unfiltered rows."""
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I",
                              zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw += rgb[row * stride:(row + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    written = render()
    print("wrote", written, os.path.getsize(written), "bytes")
