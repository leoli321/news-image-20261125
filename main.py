#!/usr/bin/env python3
"""Draw the world news of Wednesday 25 November 2026 as one 1024x1024 image.

Pure Python standard library: no Pillow, no network, no randomness.
Reads fonts.bin (bitmap glyphs extracted from local DejaVu fonts) from the
same directory, renders six verified news cards onto an RGB framebuffer,
and writes entry.png (1024x1024) to $MAKEFUN_OUTPUT_DIR (default /output).

The six stories were verified against wire reports (Reuters, SCMP) on
25 November 2026: each either happened or was first reported that day.
"""

import math
import os
import struct
import zlib

W, H = 1024, 1024

# ---- palette ------------------------------------------------------------
PAPER = (250, 246, 238)
INK = (22, 22, 22)
MUTED = (96, 92, 84)
NAVY = (27, 58, 92)
RED = (179, 38, 30)
CARD = (255, 255, 255)
CARD_LINE = (216, 210, 196)
GOLD = (176, 124, 0)
TEAL = (0, 110, 110)
FOREST = (46, 125, 50)
PLUM = (103, 58, 140)
WHITE = (255, 255, 255)

# ---- the day's news -----------------------------------------------------
# (tag, tag colour, headline, summary, source, icon)
CARDS = [
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
     "A federal jury finds Huawei guilty of fraud and conspiring to steal "
     "trade secrets in the long-running Iran sanctions case.",
     "REUTERS", "burst"),
    ("CONFLICT \u00b7 GULF", GOLD,
     "Houthis hit Riyadh\u2019s tallest tower",
     "A Houthi strike hits Riyadh\u2019s tallest tower again, wounding 11 "
     "people, in a fresh escalation across the Gulf.",
     "REUTERS", "flame"),
    ("CRIME \u00b7 LATIN AMERICA", TEAL,
     "Hostages freed in Colombia raid",
     "Police free hostages held in a Cartagena supermarket after a failed "
     "armoured-car raid; one captor is killed.",
     "REUTERS", "globe"),
    ("LABOUR \u00b7 SOUTH ASIA", FOREST,
     "Bangladesh raises garment wage 36%",
     "Bangladesh lifts garment workers\u2019 minimum wage 36% to $139 a "
     "month after weeks of protests.",
     "SCMP", "chart"),
]

DATE_LINE = "WEDNESDAY 25 NOVEMBER 2026"
MASTHEAD = "THE WORLD IN A DAY"
FOOTER = ("SOURCES: REUTERS \u00b7 SCMP"
          "  \u2014  SIX STORIES THAT DEFINED THE DAY")


# ---- bitmap fonts -------------------------------------------------------
class Font:
    def __init__(self, data):
        self.glyphs = {}
        self.size = 0
        self._parse(data)

    def _parse(self, data):
        assert data[:4] == b"FNT1"
        pos = 4
        count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        self.fonts = {}
        for _ in range(count):
            nlen = data[pos]
            pos += 1
            name = data[pos:pos + nlen].decode("ascii")
            pos += nlen
            size, nglyphs = struct.unpack_from("<II", data, pos)
            pos += 8
            glyphs = {}
            for _ in range(nglyphs):
                cp, bx, bt, w, h, adv = struct.unpack_from("<IhhHHH", data, pos)
                pos += 14
                cov = data[pos:pos + w * h]
                pos += w * h
                glyphs[cp] = (bx, bt, w, h, adv, cov)
            self.fonts[name] = (size, glyphs)

    def get(self, name):
        size, glyphs = self.fonts[name]
        return size, glyphs


class Text:
    def __init__(self, fontpack):
        self.pack = fontpack

    def measure(self, font_name, text):
        _, glyphs = self.pack.get(font_name)
        total = 0
        for ch in text:
            g = glyphs.get(ord(ch))
            if g is None:
                g = glyphs[ord("?")]
            total += g[4]
        return total

    def width(self, font_name, text):
        return self.measure(font_name, text)

    def wrap(self, font_name, text, max_width):
        """Greedy word wrap; returns a list of lines that fit max_width."""
        words = text.split(" ")
        lines = []
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if self.measure(font_name, trial) <= max_width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                # hard-split a single over-long word
                while self.measure(font_name, word) > max_width and len(word) > 1:
                    cut = 1
                    while (cut < len(word)
                           and self.measure(font_name, word[:cut + 1]) <= max_width):
                        cut += 1
                    lines.append(word[:cut])
                    word = word[cut:]
                cur = word
        if cur:
            lines.append(cur)
        return lines


# ---- canvas -------------------------------------------------------------
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)
        r, g, b = bg
        for i in range(0, len(self.buf), 3):
            self.buf[i] = r
            self.buf[i + 1] = g
            self.buf[i + 2] = b

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set_px(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.buf[i], self.buf[i + 1], self.buf[i + 2] = color

    def blend_px(self, x, y, color, alpha):
        """Alpha-blend a colour over the pixel (alpha 0..255)."""
        if alpha <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = self._idx(x, y)
        if alpha >= 255:
            self.buf[i], self.buf[i + 1], self.buf[i + 2] = color
            return
        inv = 255 - alpha
        self.buf[i] = (color[0] * alpha + self.buf[i] * inv) // 255
        self.buf[i + 1] = (color[1] * alpha + self.buf[i + 1] * inv) // 255
        self.buf[i + 2] = (color[2] * alpha + self.buf[i + 2] * inv) // 255

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        r, g, b = color
        for yy in range(y0, y1):
            base = (yy * self.w + x0) * 3
            for xx in range(x0, x1):
                i = base + (xx - x0) * 3
                self.buf[i] = r
                self.buf[i + 1] = g
                self.buf[i + 2] = b

    def hline(self, x, y, length, color):
        self.fill_rect(x, y, length, 1, color)

    def vline(self, x, y, length, color):
        self.fill_rect(x, y, 1, length, color)

    def fill_circle(self, cx, cy, r, color):
        for dy in range(-r, r + 1):
            half = int((r * r - dy * dy) ** 0.5)
            self.fill_rect(cx - half, cy + dy, half * 2 + 1, 1, color)

    def ring(self, cx, cy, r, thickness, color, bg):
        self.fill_circle(cx, cy, r, color)
        self.fill_circle(cx, cy, r - thickness, bg)

    def draw_line(self, x0, y0, x1, y1, color, width=1):
        """Bresenham line with a round brush of the given width."""
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        rad = width // 2
        for s in range(steps + 1):
            t = s / steps
            x = int(round(x0 + dx * t))
            y = int(round(y0 + dy * t))
            self.fill_circle(x, y, rad, color)

    def fill_polygon(self, points, color):
        """Non-zero winding scanline fill for a simple polygon."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        y_min = max(0, min(ys))
        y_max = min(self.h - 1, max(ys))
        edges = []
        n = len(points)
        for i in range(n):
            x0, y0 = points[i]
            x1, y1 = points[(i + 1) % n]
            if y0 == y1:
                continue
            if y0 > y1:
                x0, y0, x1, y1 = x1, y1, x0, y0
                direction = -1
            else:
                direction = 1
            edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), direction))
        for y in range(y_min, y_max + 1):
            yc = y + 0.5
            xs = []
            for y0, y1, x0, slope, direction in edges:
                if y0 <= yc < y1:
                    xs.append((x0 + (yc - y0) * slope, direction))
            xs.sort()
            winding = 0
            prev = None
            for x, direction in xs:
                if prev is not None and winding != 0:
                    xa = max(0, int(prev + 0.5))
                    xb = min(self.w, int(x + 0.5))
                    if xb > xa:
                        self.fill_rect(xa, y, xb - xa, 1, color)
                winding += direction
                prev = x

    def blit_scaled(self, src, dx, dy, dw, dh):
        """Copy src canvas scaled to dw x dh at (dx, dy), nearest neighbour."""
        for yy in range(dh):
            sy = min(src.h - 1, yy * src.h // dh)
            for xx in range(dw):
                sx = min(src.w - 1, xx * src.w // dw)
                i = self._idx(dx + xx, dy + yy)
                j = (sy * src.w + sx) * 3
                self.buf[i] = src.buf[j]
                self.buf[i + 1] = src.buf[j + 1]
                self.buf[i + 2] = src.buf[j + 2]

    def draw_text(self, text_tool, font_name, x, baseline_y, text, color):
        _, glyphs = text_tool.pack.get(font_name)
        pen = x
        for ch in text:
            g = glyphs.get(ord(ch))
            if g is None:
                g = glyphs[ord("?")]
            bx, bt, w, h, adv, cov = g
            if w and h:
                top = baseline_y - bt
                for row in range(h):
                    yy = top + row
                    if yy < 0 or yy >= self.h:
                        continue
                    base = row * w
                    for col in range(w):
                        a = cov[base + col]
                        if a:
                            self.blend_px(pen + bx + col, yy, color, a)
            pen += adv
        return pen


# ---- icons --------------------------------------------------------------
def draw_icon(cv, kind, x, y, s, color):
    """Draw a small pictogram inside a s x s box at (x, y)."""
    if kind == "globe":
        cv.ring(x + s // 2, y + s // 2, s // 2 - 2, 4, color, CARD)
        cv.draw_line(x + 8, y + s // 2, x + s - 8, y + s // 2, color, 3)
        cv.draw_line(x + s // 2, y + 8, x + s // 2, y + s - 8, color, 3)
        cv.fill_polygon([(x + s - 22, y + 14), (x + s - 4, y + 6),
                         (x + s - 10, y + 22)], RED)
    elif kind == "pill":
        # solid capsule, diagonal
        cv.draw_line(x + 10, y + s - 12, x + s - 10, y + 12, color, 20)
    elif kind == "quake":
        cv.fill_circle(x + s // 2, y + s // 2, 5, color)
        for r in (10, 17, 24):
            cv.ring(x + s // 2, y + s // 2, r, 3, color, CARD)
        cv.draw_line(x + 6, y + s - 6, x + 20, y + s - 20, color, 4)
        cv.draw_line(x + 20, y + s - 20, x + 30, y + s - 10, color, 4)
        cv.draw_line(x + 30, y + s - 10, x + s - 8, y + s - 24, color, 4)
    elif kind == "chart":
        cv.fill_rect(x + 10, y + s - 24, 10, 14, color)
        cv.fill_rect(x + 26, y + s - 36, 10, 26, color)
        cv.fill_rect(x + 42, y + s - 48, 10, 38, color)
        cv.draw_line(x + 8, y + s - 26, x + 28, y + s - 40, RED, 4)
        cv.draw_line(x + 28, y + s - 40, x + 52, y + s - 52, RED, 4)
        cv.fill_polygon([(x + 52, y + s - 52), (x + 40, y + s - 52),
                         (x + 52, y + s - 40)], RED)
    elif kind == "flame":
        cv.fill_polygon([
            (x + s // 2, y + 4), (x + s - 10, y + 26), (x + s - 6, y + 40),
            (x + s - 14, y + s - 8), (x + 14, y + s - 8), (x + 10, y + 40),
            (x + 6, y + 26),
        ], (230, 92, 0))
        cv.fill_polygon([
            (x + s // 2, y + 26), (x + s - 16, y + 40), (x + s - 12, y + s - 12),
            (x + 12, y + s - 12), (x + 16, y + 40),
        ], (255, 196, 0))
    elif kind == "burst":
        cx, cy = x + s // 2, y + s // 2
        pts = []
        for i in range(16):
            ang = 3.14159265 * i / 8.0
            r = (s // 2 - 2) if i % 2 == 0 else (s // 5)
            pts.append((int(cx + r * math.cos(ang)),
                        int(cy + r * math.sin(ang))))
        cv.fill_polygon(pts, color)
        cv.fill_circle(cx, cy, 7, WHITE)


# ---- layout -------------------------------------------------------------
def draw_card(cv, txt, x, y, w, h, card):
    tag, tag_color, headline, summary, source, icon = card
    cv.fill_rect(x, y, w, h, CARD)
    cv.fill_rect(x, y, w, 6, tag_color)
    # hairline border
    cv.hline(x, y + h - 1, w, CARD_LINE)
    cv.vline(x, y, h, CARD_LINE)
    cv.vline(x + w - 1, y, h, CARD_LINE)
    cv.hline(x, y, w, CARD_LINE)
    pad = 18
    # kicker, with the pictogram at its right (drawn at 60px, blitted to 44)
    cv.draw_text(txt, "bold16", x + pad, y + 16 + 16, tag, tag_color)
    ic = Canvas(60, 60, CARD)
    draw_icon(ic, icon, 0, 0, 60, tag_color)
    cv.blit_scaled(ic, x + w - pad - 44, y + 8, 44, 44)
    # headline (2 lines max, full card width now the icon is out of the way)
    head_w = w - pad * 2
    lines = txt.wrap("bold30", headline, head_w)[:2]
    hy = y + 52
    for line in lines:
        cv.draw_text(txt, "bold30", x + pad, hy + 30, line, INK)
        hy += 36
    # summary (3 lines max)
    sum_y = y + 52 + 2 * 36 + 8
    slines = txt.wrap("reg20", summary, w - pad * 2)[:3]
    sy = sum_y
    for line in slines:
        cv.draw_text(txt, "reg20", x + pad, sy + 20, line, (58, 58, 58))
        sy += 26
    # footer: rule + source
    fy = y + h - 34
    cv.hline(x + pad, fy, w - pad * 2, CARD_LINE)
    cv.draw_text(txt, "bold16", x + pad, fy + 24, "SOURCE: " + source,
                 tag_color)


def build():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fonts.bin"), "rb") as f:
        pack = Font(f.read())
    txt = Text(pack)
    cv = Canvas(W, H, PAPER)

    # masthead
    cv.fill_rect(0, 0, W, 112, NAVY)
    title_w = txt.width("bold46", MASTHEAD)
    cv.draw_text(txt, "bold46", (W - title_w) // 2, 76, MASTHEAD, WHITE)
    cv.fill_rect(0, 112, W, 4, GOLD)
    # dateline strip
    cv.fill_rect(0, 116, W, 44, RED)
    date_w = txt.width("bold21", DATE_LINE)
    cv.draw_text(txt, "bold21", (W - date_w) // 2, 116 + 34, DATE_LINE, WHITE)

    # cards: 2 columns x 3 rows
    margin = 24
    gap = 18
    cw = (W - margin * 2 - gap) // 2
    ch = 261
    top = 172
    # guard: no headline may exceed its 2 lines and no summary its 3,
    # so an over-long text fails loudly here instead of clipping silently
    for card in CARDS:
        assert len(txt.wrap("bold30", card[2], cw - 36)) <= 2, card[2]
        assert len(txt.wrap("reg20", card[3], cw - 36)) <= 3, card[2]
    for i, card in enumerate(CARDS):
        col = i % 2
        row = i // 2
        x = margin + col * (cw + gap)
        y = top + row * (ch + gap)
        draw_card(cv, txt, x, y, cw, ch, card)

    # footer
    fw = txt.width("reg14", FOOTER)
    cv.draw_text(txt, "reg14", (W - fw) // 2, 1014, FOOTER, MUTED)

    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    with open(out_path, "wb") as f:
        f.write(encode_png(W, H, bytes(cv.buf)))
    return out_path


def encode_png(width, height, rgb):
    """Minimal deterministic PNG encoder (8-bit RGB, filter 0 rows)."""
    def chunk(kind, payload):
        out = struct.pack(">I", len(payload)) + kind + payload
        out += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]
    idat = zlib.compress(bytes(raw), 9)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", idat)
    png += chunk(b"IEND", b"")
    return png


if __name__ == "__main__":
    path = build()
    print("wrote", path, os.path.getsize(path), "bytes")
