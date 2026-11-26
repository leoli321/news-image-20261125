#!/usr/bin/env python3
"""Extract the bitmap font pack (fonts.bin) that main.py renders with.

The pack is built once, offline, from the DejaVu Sans and DejaVu Sans
Bold TrueType files installed on this machine, and then committed next
to main.py so the entry itself needs nothing but the standard library.
This script is the tool that produced it; running it again regenerates
the same pack:

    python3 extract_fonts.py [output-path]

Only the glyphs the news page can print are packed: printable ASCII
plus the handful of punctuation marks the headlines use.  Each glyph is
rasterised with 4x4 supersampling, so the coverage byte per pixel runs
0..255 and the renderer can alpha-blend text smoothly.

Pack layout (all integers little-endian), read by main.py:
    "FNT1", u32 font count
    per font:  u8 name length, name bytes, u32 pixel size,
               u32 glyph count
    per glyph: u32 codepoint, i16 bearing x, i16 bearing top,
               u16 width, u16 height, u16 advance,
               width*height coverage bytes, row by row from the top
"""

import struct
import sys

SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# (pack name, TTF path, pixel size)
JOBS = [
    ("bold46", SANS_BOLD, 46),
    ("bold30", SANS_BOLD, 30),
    ("bold21", SANS_BOLD, 21),
    ("bold16", SANS_BOLD, 16),
    ("reg20", SANS, 20),
    ("reg14", SANS, 14),
]

# Printable ASCII plus the punctuation the page actually uses:
# (c), middle dot, en/em dashes, curly quotes, ellipsis, euro sign.
CODEPOINTS = (list(range(32, 127))
              + [169, 183, 8211, 8212, 8216, 8217, 8220, 8221, 8230, 8364])

SUPERSAMPLE = 4


class Face:
    """Just enough of a TrueType reader to walk glyph outlines."""

    def __init__(self, blob):
        self.blob = blob
        self.tables = {}
        count = struct.unpack_from(">H", blob, 4)[0]
        for i in range(count):
            off = 12 + i * 16
            tag = blob[off:off + 4].decode("latin-1")
            start, length = struct.unpack_from(">II", blob, off + 8)
            self.tables[tag] = (start, length)
        head = self._table("head")
        self.units_per_em = struct.unpack_from(">H", head, 18)[0]
        self.index_to_loc = struct.unpack_from(">h", head, 50)[0]
        maxp = self._table("maxp")
        self.num_glyphs = struct.unpack_from(">H", maxp, 4)[0]
        hhea = self._table("hhea")
        self.num_h_metrics = struct.unpack_from(">H", hhea, 34)[0]
        self._build_cmap()

    def _table(self, tag):
        start, length = self.tables[tag]
        return self.blob[start:start + length]

    def _build_cmap(self):
        """Map codepoints to glyph ids through the format 4 subtable."""
        cmap = self._table("cmap")
        subtables = struct.unpack_from(">H", cmap, 2)[0]
        chosen = None
        for i in range(subtables):
            platform, encoding, offset = struct.unpack_from(
                ">HHI", cmap, 4 + i * 8)
            fmt = struct.unpack_from(">H", cmap, offset)[0]
            if fmt == 4 and (platform, encoding) in ((3, 1), (0, 3),
                                                     (0, 4), (3, 0)):
                chosen = offset
                break
            if fmt == 4 and chosen is None:
                chosen = offset
        if chosen is None:
            raise ValueError("no format 4 cmap subtable")
        seg_count = struct.unpack_from(">H", cmap, chosen + 6)[0] // 2
        base = chosen + 14
        ends = struct.unpack_from(">%dH" % seg_count, cmap, base)
        base += 2 * seg_count + 2
        starts = struct.unpack_from(">%dH" % seg_count, cmap, base)
        base += 2 * seg_count
        deltas = struct.unpack_from(">%dh" % seg_count, cmap, base)
        base += 2 * seg_count
        range_off_at = base
        offsets = struct.unpack_from(">%dH" % seg_count, cmap, base)
        self.cmap = (starts, ends, deltas, offsets, cmap, range_off_at)

    def glyph_id(self, codepoint):
        starts, ends, deltas, offsets, cmap, range_off_at = self.cmap
        for i in range(len(ends)):
            if starts[i] <= codepoint <= ends[i]:
                if offsets[i] == 0:
                    return (codepoint + deltas[i]) % 65536
                addr = (range_off_at + 2 * i + offsets[i]
                        + 2 * (codepoint - starts[i]))
                gid = struct.unpack_from(">H", cmap, addr)[0]
                return (gid + deltas[i]) % 65536 if gid else 0
        return 0

    def glyph_offset(self, gid):
        loca = self._table("loca")
        if self.index_to_loc == 1:
            return struct.unpack_from(">I", loca, gid * 4)[0]
        return struct.unpack_from(">H", loca, gid * 2)[0] * 2

    def advance(self, gid):
        hmtx = self._table("hmtx")
        gid = min(gid, self.num_h_metrics - 1)
        return struct.unpack_from(">H", hmtx, gid * 4)[0]

    def outline(self, gid):
        """Return (contours, x_min, y_min, x_max, y_max) in font units.

        Contours are lists of (x, y, on_curve) points with implied
        on-curve midpoints inserted between off-curve neighbours, so
        callers only ever see quadratic segments.
        """
        start = self.glyph_offset(gid)
        end = self.glyph_offset(gid + 1)
        if start == end:
            return [], 0, 0, 0, 0
        glyf = self.tables["glyf"][0] + start
        blob = self.blob
        n_contours, x_min, y_min, x_max, y_max = struct.unpack_from(
            ">hHHHH", blob, glyf)
        x_min = struct.unpack_from(">h", blob, glyf + 2)[0]
        y_min = struct.unpack_from(">h", blob, glyf + 4)[0]
        x_max = struct.unpack_from(">h", blob, glyf + 6)[0]
        y_max = struct.unpack_from(">h", blob, glyf + 8)[0]
        if n_contours < 0:
            return self._composite(glyf, x_min, y_min, x_max, y_max)
        pos = glyf + 10
        ends = struct.unpack_from(">%dH" % n_contours, blob, pos)
        pos += 2 * n_contours
        ins_len = struct.unpack_from(">H", blob, pos)[0]
        pos += 2 + ins_len
        total = ends[-1] + 1
        flags = []
        while len(flags) < total:
            flag = blob[pos]
            pos += 1
            flags.append(flag)
            if flag & 0x08:
                repeat = blob[pos]
                pos += 1
                flags.extend([flag] * repeat)
        xs = []
        value = 0
        for flag in flags:
            if flag & 0x02:
                step = blob[pos]
                pos += 1
                value += step if flag & 0x10 else -step
            elif not flag & 0x10:
                value += struct.unpack_from(">h", blob, pos)[0]
                pos += 2
            xs.append(value)
        ys = []
        value = 0
        for flag in flags:
            if flag & 0x04:
                step = blob[pos]
                pos += 1
                value += step if flag & 0x20 else -step
            elif not flag & 0x20:
                value += struct.unpack_from(">h", blob, pos)[0]
                pos += 2
            ys.append(value)
        contours = []
        first = 0
        for last in ends:
            raw = [(xs[i], ys[i], bool(flags[i] & 0x01))
                   for i in range(first, last + 1)]
            contours.append(_normalise(raw))
            first = last + 1
        return contours, x_min, y_min, x_max, y_max

    def _composite(self, glyf, x_min, y_min, x_max, y_max):
        """Flatten a composite glyph by placing each component's outline."""
        blob = self.blob
        pos = glyf + 10
        contours = []
        while True:
            flags, component = struct.unpack_from(">HH", blob, pos)
            pos += 4
            if flags & 0x0001:
                dx, dy = struct.unpack_from(">hh", blob, pos)
                pos += 4
            else:
                dx, dy = blob[pos], blob[pos + 1]
                pos += 2
            scale = 1.0
            if flags & 0x0008:
                scale = struct.unpack_from(">h", blob, pos)[0] / 16384.0
                pos += 2
            elif flags & 0x0040:
                pos += 4
            elif flags & 0x0080:
                pos += 8
            sub, _, _, _, _ = self.outline(component)
            for contour in sub:
                contours.append([(round(x * scale) + dx,
                                  round(y * scale) + dy, on)
                                 for x, y, on in contour])
            if not flags & 0x0020:
                return contours, x_min, y_min, x_max, y_max


def _normalise(raw):
    """Expand a raw contour so consecutive points form quad segments."""
    if not raw:
        return raw
    points = list(raw)
    if not points[0][2]:
        if points[-1][2]:
            points = [points[-1]] + points[:-1]
        else:
            mid = ((points[0][0] + points[-1][0]) // 2,
                   (points[0][1] + points[-1][1]) // 2, True)
            points = [mid] + points
    out = [points[0]]
    for point in points[1:]:
        if not point[2] and not out[-1][2]:
            mid = ((point[0] + out[-1][0]) // 2,
                   (point[1] + out[-1][1]) // 2, True)
            out.append(mid)
        out.append(point)
    return out


def _flatten(contours, scale, x0, y_top):
    """Turn font-unit contours into closed pixel-space polylines."""
    lines = []
    for contour in contours:
        pts = [(x * scale - x0, y_top - y * scale)
               for x, y, _ in contour]
        on = [flag for _, _, flag in contour]
        path = [pts[0]]
        i = 1
        while i <= len(pts):
            nxt = pts[i % len(pts)]
            if on[i % len(pts)]:
                path.append(nxt)
                i += 1
            else:
                end = pts[(i + 1) % len(pts)]
                for step in range(1, 9):
                    t = step / 8.0
                    mx = (1 - t) ** 2 * path[-1][0] \
                        + 2 * (1 - t) * t * nxt[0] + t * t * end[0]
                    my = (1 - t) ** 2 * path[-1][1] \
                        + 2 * (1 - t) * t * nxt[1] + t * t * end[1]
                    path.append((mx, my))
                i += 2
        lines.append(path)
    return lines


def _inside(lines, px, py):
    """Even-odd point-in-polygon test over every flattened contour."""
    inside = False
    for path in lines:
        prev = path[-1]
        for point in path:
            x1, y1 = prev
            x2, y2 = point
            if (y1 > py) != (y2 > py):
                cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if px < cross:
                    inside = not inside
            prev = point
    return inside


def rasterise(face, gid, size):
    """Render one glyph; return (bx, bt, w, h, advance, coverage bytes)."""
    import math
    scale = size / face.units_per_em
    advance = round(face.advance(gid) * scale)
    contours, x_min, y_min, x_max, y_max = face.outline(gid)
    if not contours:
        return 0, 0, 0, 0, advance, b""
    x0 = math.floor(x_min * scale)
    x1 = math.ceil(x_max * scale)
    y_top = math.ceil(y_max * scale)
    y_bot = math.floor(y_min * scale)
    w = x1 - x0
    h = y_top - y_bot
    lines = _flatten(contours, scale, x0, y_top)
    coverage = bytearray(w * h)
    ss = SUPERSAMPLE
    for row in range(h):
        for col in range(w):
            hits = 0
            for sy in range(ss):
                for sx in range(ss):
                    if _inside(lines, col + (sx + 0.5) / ss,
                               row + (sy + 0.5) / ss):
                        hits += 1
            coverage[row * w + col] = hits * 255 // (ss * ss)
    return x0, y_top, w, h, advance, bytes(coverage)


def build_pack():
    faces = {}
    out = bytearray()
    out += b"FNT1"
    out += struct.pack("<I", len(JOBS))
    for name, path, size in JOBS:
        if path not in faces:
            with open(path, "rb") as handle:
                faces[path] = Face(handle.read())
        face = faces[path]
        glyphs = []
        for codepoint in CODEPOINTS:
            gid = face.glyph_id(codepoint)
            bx, bt, w, h, adv, cov = rasterise(face, gid, size)
            glyphs.append((codepoint, bx, bt, w, h, adv, cov))
        encoded = name.encode("ascii")
        out += struct.pack("<B", len(encoded)) + encoded
        out += struct.pack("<II", size, len(glyphs))
        for codepoint, bx, bt, w, h, adv, cov in glyphs:
            out += struct.pack("<IhhHHH", codepoint, bx, bt, w, h, adv)
            out += cov
    return bytes(out)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "fonts.bin"
    pack = build_pack()
    with open(target, "wb") as handle:
        handle.write(pack)
    print("wrote", target, len(pack), "bytes")
