#!/usr/bin/env python3
"""Extract bitmap glyphs from local DejaVu TrueType fonts into fonts.bin.

Pure standard library. Parses TTF tables (head/maxp/hhea/hmtx/loca/glyf/cmap
format 4), flattens quadratic outlines, rasterises them with 4x supersampling
and a non-zero winding scanline fill, and writes a compact binary font pack
that main.py reads at run time.

Output format (fonts.bin):
  magic "FNT1", u32 font_count
  per font: u8 name_len, name bytes, u32 size_px, u32 glyph_count
  per glyph: u32 codepoint, i16 bearing_x, i16 bearing_top,
             u16 width, u16 height, u16 advance, width*height coverage bytes
All integers little-endian. Coverage 0..255 (0 = transparent).
"""

import struct
import sys

SS = 4  # supersampling factor

CHARSET = (
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "\u2014\u2013\u2018\u2019\u201c\u201d\u2022\u00b7\u2026\u00b0"
)

FONTS = [
    ("bold46", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46),
    ("bold30", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30),
    ("bold21", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 21),
    ("bold16", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16),
    ("reg20", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20),
    ("reg14", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14),
]


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


class TTF:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        d = self.data
        assert u32(d, 0) == 0x00010000, "not a TrueType font"
        n = u16(d, 4)
        self.tables = {}
        for i in range(n):
            o = 12 + i * 16
            tag = d[o:o + 4].decode("latin-1")
            self.tables[tag] = (u32(d, o + 8), u32(d, o + 12))
        head = self._table("head")
        self.units_per_em = u16(head, 18)
        self.index_to_loc_format = i16(head, 50)
        maxp = self._table("maxp")
        self.num_glyphs = u16(maxp, 4)
        hhea = self._table("hhea")
        self.num_hmetrics = u16(hhea, 34)
        self._cmap = self._parse_cmap()

    def _table(self, tag):
        off, length = self.tables[tag]
        return self.data[off:off + length]

    def _parse_cmap(self):
        cmap = self._table("cmap")
        n = u16(cmap, 2)
        best = None
        for i in range(n):
            o = 4 + i * 8
            platform, encoding = u16(cmap, o), u16(cmap, o + 2)
            sub_off = u32(cmap, o + 4)
            fmt = u16(cmap, sub_off)
            if fmt == 12:
                best = ("12", sub_off)
                break
            if fmt == 4 and best is None:
                best = ("4", sub_off)
        if best is None:
            raise ValueError("no cmap format 4 or 12")
        kind, off = best
        mapping = {}
        if kind == "4":
            seg_count = u16(cmap, off + 6) // 2
            end_base = off + 14
            start_base = end_base + 2 * seg_count + 2
            delta_base = start_base + 2 * seg_count
            range_base = delta_base + 2 * seg_count
            glyph_base = range_base + 2 * seg_count
            for s in range(seg_count):
                end = u16(cmap, end_base + 2 * s)
                start = u16(cmap, start_base + 2 * s)
                delta = i16(cmap, delta_base + 2 * s)
                ro = u16(cmap, range_base + 2 * s)
                if start == 0xFFFF and end == 0xFFFF:
                    continue
                for cp in range(start, end + 1):
                    if ro == 0:
                        gid = (cp + delta) % 65536
                    else:
                        idx = range_base + 2 * s + ro + 2 * (cp - start)
                        gid = u16(cmap, idx)
                        if gid:
                            gid = (gid + delta) % 65536
                    if gid:
                        mapping[cp] = gid
        else:  # format 12
            n_groups = u32(cmap, off + 12)
            for g in range(n_groups):
                go = off + 16 + g * 12
                start, end = u32(cmap, go), u32(cmap, go + 4)
                gid0 = u32(cmap, go + 8)
                for cp in range(start, end + 1):
                    mapping[cp] = gid0 + (cp - start)
        return mapping

    def glyph_id(self, cp):
        return self._cmap.get(cp, 0)

    def advance(self, gid):
        hmtx = self._table("hmtx")
        if gid < self.num_hmetrics:
            return u16(hmtx, gid * 4)
        return u16(hmtx, (self.num_hmetrics - 1) * 4)

    def _glyph_offset(self, gid):
        loca = self._table("loca")
        if self.index_to_loc_format == 0:
            o0 = u16(loca, gid * 2) * 2
            o1 = u16(loca, (gid + 1) * 2) * 2
        else:
            o0 = u32(loca, gid * 4)
            o1 = u32(loca, (gid + 1) * 4)
        return o0, o1

    def outline(self, gid, depth=0):
        """Return list of contours; each contour is a list of (x, y, on_curve)."""
        if depth > 4:
            return []
        glyf = self._table("glyf")
        o0, o1 = self._glyph_offset(gid)
        if o1 <= o0:
            return []
        n_contours = i16(glyf, o0)
        if n_contours >= 0:
            return self._simple_outline(glyf, o0, n_contours)
        # composite glyph
        contours = []
        p = o0 + 10
        while True:
            flags = u16(glyf, p)
            comp = u16(glyf, p + 2)
            p += 4
            if flags & 0x0001:  # words
                dx, dy = i16(glyf, p), i16(glyf, p + 2)
                p += 4
            else:
                dx = struct.unpack_from(">b", glyf, p)[0]
                dy = struct.unpack_from(">b", glyf, p + 1)[0]
                p += 2
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 0x0008:  # scale
                s = struct.unpack_from(">h", glyf, p)[0] / 16384.0
                a, d = s, s
                p += 2
            elif flags & 0x0040:  # x/y scale
                a = struct.unpack_from(">h", glyf, p)[0] / 16384.0
                d = struct.unpack_from(">h", glyf, p + 2)[0] / 16384.0
                p += 4
            elif flags & 0x0080:  # 2x2
                a = struct.unpack_from(">h", glyf, p)[0] / 16384.0
                b = struct.unpack_from(">h", glyf, p + 2)[0] / 16384.0
                c = struct.unpack_from(">h", glyf, p + 4)[0] / 16384.0
                d = struct.unpack_from(">h", glyf, p + 6)[0] / 16384.0
                p += 8
            for contour in self.outline(comp, depth + 1):
                contours.append([
                    (a * x + c * y + dx, b * x + d * y + dy, on)
                    for (x, y, on) in contour
                ])
            if not (flags & 0x0020):
                break
        return contours

    def _simple_outline(self, glyf, o0, n_contours):
        p = o0 + 10
        end_pts = [u16(glyf, p + 2 * i) for i in range(n_contours)]
        p += 2 * n_contours
        instr_len = u16(glyf, p)
        p += 2 + instr_len
        n_points = end_pts[-1] + 1 if end_pts else 0
        flags = []
        while len(flags) < n_points:
            f = glyf[p]
            p += 1
            flags.append(f)
            if f & 0x08:  # repeat
                rep = glyf[p]
                p += 1
                flags.extend([f] * rep)
        xs = []
        x = 0
        for f in flags:
            if f & 0x02:  # x short
                dx = glyf[p]
                p += 1
                x += dx if (f & 0x10) else -dx
            elif not (f & 0x10):
                dx = i16(glyf, p)
                p += 2
                x += dx
            xs.append(x)
        ys = []
        y = 0
        for f in flags:
            if f & 0x04:  # y short
                dy = glyf[p]
                p += 1
                y += dy if (f & 0x20) else -dy
            elif not (f & 0x20):
                dy = i16(glyf, p)
                p += 2
                y += dy
            ys.append(y)
        contours = []
        start = 0
        for end in end_pts:
            contour = [
                (xs[i], ys[i], bool(flags[i] & 0x01))
                for i in range(start, end + 1)
            ]
            contours.append(contour)
            start = end + 1
        return contours


def flatten_contour(contour):
    """Expand quadratic segments into a polyline of (x, y) points."""
    seq = contour[:]
    if not seq:
        return []
    # Rotate so we start at an on-curve point (implied midpoint if needed).
    if not seq[0][2]:
        lx, ly, _ = seq[-1]
        fx, fy, _ = seq[0]
        seq = [((lx + fx) / 2.0, (ly + fy) / 2.0, True)] + seq
    out = [(seq[0][0], seq[0][1])]
    i = 1
    while i < len(seq):
        x, y, on = seq[i]
        if on:
            out.append((x, y))
            i += 1
        else:
            # off-curve control point; next point is on-curve or implied
            cx, cy = x, y
            if i + 1 < len(seq):
                nx, ny, non = seq[i + 1]
                if non:
                    ex, ey = nx, ny
                    i += 2
                else:
                    ex, ey = (cx + nx) / 2.0, (cy + ny) / 2.0
                    i += 1
            else:
                ex, ey = out[0]
                i += 1
            sx, sy = out[-1]
            # subdivide quadratic
            dist = abs(cx - sx) + abs(cy - sy) + abs(ex - cx) + abs(ey - cy)
            steps = max(2, int(dist / 24) + 1)
            for s in range(1, steps + 1):
                t = s / steps
                mt = 1 - t
                out.append((
                    mt * mt * sx + 2 * mt * t * cx + t * t * ex,
                    mt * mt * sy + 2 * mt * t * cy + t * t * ey,
                ))
    return out


def rasterise(polys, width, height):
    """Non-zero winding scanline fill at SS supersampling; returns coverage bytes."""
    # Build edge list in supersampled space: (y_min, y_max, x_at_ymin, dx/dy, direction)
    edges = []
    W, H = width * SS, height * SS
    for poly in polys:
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            if y0 > y1:
                x0, y0, x1, y1 = x1, y1, x0, y0
                direction = -1
            else:
                direction = 1
            edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), direction))
    edges.sort(key=lambda e: e[0])
    cov = bytearray(width * height)
    # supersampled coverage accumulation
    acc = [[0] * width for _ in range(height)]
    active = []
    ei = 0
    for row in range(H):
        y = row + 0.5
        while ei < len(edges) and edges[ei][0] <= y:
            active.append(edges[ei])
            ei += 1
        active = [e for e in active if e[1] > y]
        if not active:
            continue
        xs = sorted((e[2] + (y - e[0]) * e[3], e[4]) for e in active)
        winding = 0
        prev_x = None
        for x, direction in xs:
            if prev_x is not None and winding != 0:
                x0 = max(0.0, prev_x)
                x1 = min(float(W), x)
                if x1 > x0:
                    # accumulate coverage for the pixel columns spanned
                    col0 = int(x0 // SS)
                    col1 = int((x1 - 1e-9) // SS)
                    for col in range(col0, col1 + 1):
                        lo = max(x0, col * SS)
                        hi = min(x1, (col + 1) * SS)
                        if hi > lo:
                            acc[row // SS][col] += (hi - lo) / SS
            winding += direction
            prev_x = x
    for r in range(height):
        for c in range(width):
            v = acc[r][c] / SS
            cov[r * width + c] = max(0, min(255, int(round(v * 255))))
    return bytes(cov)


def extract(font_path, size_px, charset):
    font = TTF(font_path)
    scale = size_px / font.units_per_em
    glyphs = []
    missing = []
    for ch in charset:
        cp = ord(ch)
        gid = font.glyph_id(cp)
        if gid == 0:
            missing.append(ch)
            continue
        contours = font.outline(gid)
        polys = [flatten_contour(c) for c in contours]
        polys = [p for p in polys if len(p) >= 2]
        adv = font.advance(gid)
        advance = int(round(adv * scale))
        if not polys:
            # space or empty glyph: no bitmap, keep advance only
            glyphs.append((cp, 0, 0, 0, 0, advance, b""))
            continue
        xs = [p[0] for poly in polys for p in poly]
        ys = [p[1] for poly in polys for p in poly]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        # bitmap box in font units, padded by 1 font unit each side
        bx0 = int(x_min * scale) - 1
        bx1 = int(x_max * scale) + 2
        by1 = int(y_max * scale) + 2  # top (font y up)
        by0 = int(y_min * scale) - 1  # bottom
        w = bx1 - bx0
        h = by1 - by0
        # shift polys into bitmap space, y down, supersampled
        shifted = []
        for poly in polys:
            shifted.append([
                ((x * scale - bx0) * SS, (by1 - y * scale) * SS)
                for (x, y) in poly
            ])
        cov = rasterise(shifted, w, h)
        bearing_x = bx0
        bearing_top = by1
        glyphs.append((cp, bearing_x, bearing_top, w, h, advance, cov))
    return glyphs, missing


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "fonts.bin"
    buf = bytearray()
    buf += b"FNT1"
    buf += struct.pack("<I", len(FONTS))
    for name, path, size in FONTS:
        glyphs, missing = extract(path, size, CHARSET)
        if missing:
            print(f"WARNING {name}: missing glyphs: {missing!r}", file=sys.stderr)
        name_b = name.encode("ascii")
        buf += struct.pack("<B", len(name_b)) + name_b
        buf += struct.pack("<II", size, len(glyphs))
        for cp, bx, bt, w, h, adv, cov in glyphs:
            buf += struct.pack("<IhhHHH", cp, bx, bt, w, h, adv)
            buf += cov
        print(f"{name}: {len(glyphs)} glyphs, size {size}px")
    with open(out_path, "wb") as f:
        f.write(buf)
    print(f"wrote {out_path}: {len(buf)} bytes")


if __name__ == "__main__":
    main()
