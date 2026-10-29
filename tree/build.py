"""Builds the animated "literal file tree" banner for the GitHub profile.

Your public repos are folders beside a pixel-art branch. The camera opens each
project in turn: a mossy limb grows out of the folder carrying that repo's
real files, then one of its subfolders opens the same way, and the camera
glides back to the trunk for the next project. See tree/RULES.md for the look.

Edit tree/config.json, then run:  python tree/build.py
  projects     "auto" (newest public repos) or a list of repo names
  max_projects how many repos "auto" picks
  exclude      repos "auto" should skip
  root_files   extra files floating by the trunk
  max_files    items shown inside each opened folder

Options: --still out.png [seconds]   render one frame
         --sheet out.png             render a contact sheet of the whole loop
         --offline                   reuse tree/.cache.json instead of calling GitHub
Set GITHUB_TOKEN to avoid the API's anonymous rate limit.
"""
import bisect
import json
import math
import os
import random
import re
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------------- look (see RULES.md) ----------------
W, H = 1280, 660
FPS = 15
P, DOT = 4, 3                                  # 4 px cells painted as 3 px dots
PAGE = (13, 17, 23)                            # #0D1117
WIN = (22, 27, 34)                             # #161B22
BORDER = (48, 54, 61)
TEXT = (139, 148, 158)
TEXT_DIM = (110, 118, 129)
TEXT_HI = (240, 246, 252)
WX0, WY0, WX1, WY1 = 40, 30, W - 40, H - 30
TITLE_H, FOOT_H = 46, 32
CX0, CY0, CX1, CY1 = WX0 + 2, WY0 + TITLE_H + 2, WX1 - 2, WY1 - FOOT_H
CW, CH = CX1 - CX0, CY1 - CY0
ICON = 1.3

BARK_TOP = [((170, 162, 148), 6), ((143, 138, 128), 2)]
BARK_CORE = [((143, 138, 128), 52), ((122, 98, 78), 18), ((145, 149, 83), 9), ((40, 34, 31), 9),
             ((150, 52, 42), 4), ((184, 118, 62), 3), ((119, 116, 113), 5)]
BARK_UNDER = [((74, 60, 52), 6), ((30, 25, 23), 4)]
MOSS = [((146, 204, 40), 34), ((184, 226, 52), 20), ((226, 232, 70), 8), ((98, 162, 36), 26),
        ((60, 112, 34), 10), ((145, 149, 83), 2)]
TIP = [(166, 214, 40), (232, 236, 70), (205, 232, 60)]
TEXT_FILES = (".md", ".txt", ".py", ".js", ".ts", ".tsx", ".json", ".toml", ".yml", ".yaml", ".rs", ".go",
              ".java", ".c", ".cpp", ".h", ".html", ".css", ".pdf", ".ipynb", ".sh", ".cfg", ".ini", ".lock")


def font(size, weight):
    f = ImageFont.truetype(os.path.join(HERE, "fonts", "Inter.ttf"), size)
    f.set_variation_by_name(weight)
    return f


LABEL = font(19, "Medium")
TITLE = font(15, "SemiBold")
SMALL = font(12, "Regular")
_probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def text_w(s, f=LABEL):
    return _probe.textlength(s, font=f)


def hash01(a, b, salt=0):
    """Deterministic per-cell randomness, so a cell keeps its colour every frame."""
    h = (a * 374761393 + b * 668265263 + salt * 1442695041) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / 0x1000000


def pick(weighted, u):
    total = sum(w for _, w in weighted)
    u *= total
    for c, w in weighted:
        u -= w
        if u <= 0:
            return c
    return weighted[-1][0]


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)          # smootherstep


# ---------------- data ----------------
SUB_PREFERENCE = ["src", "app", "lib", "backend", "frontend", "core", "server", "client", "notebooks", "scripts"]


def api(path):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "file-tree-banner"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def listing(entries):
    entries = [e for e in entries if not e["name"].startswith(".")]
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))   # folders first, like Finder
    return [("folder" if e["type"] == "dir" else "file", e["name"] + ("/" if e["type"] == "dir" else ""))
            for e in entries]


def fetch(cfg):
    user = cfg["user"]
    if cfg["projects"] == "auto":
        repos = [r for r in api(f"/users/{user}/repos?per_page=100&sort=pushed")
                 if not r["fork"] and not r["archived"] and not r["private"]
                 and r["name"] not in cfg.get("exclude", [])]
        names = [r["name"] for r in repos][: cfg.get("max_projects", 4)]
    else:
        names = list(cfg["projects"])
    projects = []
    for name in names:
        try:
            items = listing(api(f"/repos/{user}/{name}/contents"))
        except Exception as e:                      # private, empty or missing repo
            print(f"  skipping {name}: {e}")
            continue
        dirs = [n[:-1] for k, n in items if k == "folder"]
        sub = next((d for d in SUB_PREFERENCE if d in dirs), dirs[0] if dirs else None)
        sub_items = []
        if sub:
            try:
                sub_items = listing(api(f"/repos/{user}/{name}/contents/{sub}"))
            except Exception:
                sub = None
        projects.append({"name": name, "items": items, "sub": sub, "sub_items": sub_items})
    return projects


# ---------------- branches ----------------
class Branch:
    """A grown curve: one point per pixel of length, each with its heading."""

    def __init__(self, pts, w0, w1, kind, moss):
        self.pts, self.w0, self.w1, self.kind, self.moss = pts, w0, w1, kind, moss
        self.L = len(pts)
        self.born0, self.dur = 0.0, 1.0
        self.time_fn = None                          # optional custom growth clock (the trunk)

    def at(self, s):
        return self.pts[max(0, min(int(s), self.L - 1))]

    def width(self, s):
        return self.w0 + (self.w1 - self.w0) * (s / self.L) ** 0.8

    def time(self, s):
        if self.time_fn:
            return self.time_fn(self.at(s)[0])
        return self.born0 + self.dur * s / self.L


def grow(rng, start, heading, length, target, pull=0.012, wobble=0.0025):
    """Walks 1 px at a time; the heading eases toward `target` and wobbles slowly,
    which gives the long arcs and soft S-curves of the reference."""
    phases = [rng.uniform(0, 6.28) for _ in range(3)]
    waves = [rng.uniform(90, 160), rng.uniform(170, 280), rng.uniform(300, 480)]
    x, y = start
    th = heading
    pts = []
    for i in range(int(length)):
        pts.append((x, y, th))
        wob = sum(math.sin(i / wv * 6.283 + ph) for wv, ph in zip(waves, phases)) / 3
        th += pull * (target - th) + wobble * wob
        x += math.cos(th)
        y += math.sin(th)
    return pts


def trunk_y(x):
    return 64 * math.sin(x / 290 + 0.2) + 16 * math.sin(x / 120 + 2.0)


def trunk_branch():
    pts = []
    for x in range(-700, int(CW) + 700):
        y = trunk_y(x)
        th = math.atan2(trunk_y(x + 1) - y, 1)
        pts.append((float(x), y, th))
    return Branch(pts, 11, 6, "trunk", 0.9)


# ---------------- items ----------------
class Item:
    def __init__(self, kind, name, cx, cy, label_below=False):
        """cx, cy is the centre of the icon."""
        self.kind, self.name = kind, name
        self.w, self.h = 34 * ICON, 28 * ICON
        self.ix, self.iy = cx - self.w / 2, cy - self.h / 2
        tw = text_w(name)
        if label_below:
            self.lx, self.ly, self.anchor = cx, self.iy + self.h + 15, "mm"
            self.box = (min(self.ix, cx - tw / 2) - 6, self.iy - 6, max(self.ix + self.w, cx + tw / 2) + 6, self.ly + 13)
            self.label_box = (cx - tw / 2 - 4, self.ly - 12, cx + tw / 2 + 4, self.ly + 12)
        else:
            self.lx, self.ly, self.anchor = self.ix + self.w + 10, cy + 1, "lm"
            self.box = (self.ix - 6, self.iy - 6, self.lx + tw + 8, self.iy + self.h + 6)
            self.label_box = (self.lx - 4, cy - 13, self.lx + tw + 6, cy + 13)
        self.cx, self.cy = cx, cy
        self.born = 0.0
        self.base = False                          # True once a limb grows out of this folder


def overlap(a, b, pad):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def box_dist(box, x, y):
    dx = max(box[0] - x, 0, x - box[2])
    dy = max(box[1] - y, 0, y - box[3])
    return math.hypot(dx, dy)


# ---------------- world ----------------
class World:
    def __init__(self, projects, cfg, seed=7):
        self.rng = rng = random.Random(seed)
        self.max_files = cfg.get("max_files", 6)
        self.branches, self.items = [], []
        self.samples = []                          # (x, y, half width) along every branch, for spacing
        self.trunk = trunk_branch()
        self._add_branch(self.trunk)
        self.home = (CW / 2, 0.0)

        # top level: projects float beside the trunk, alternating above and below
        n = max(len(projects), 1)
        self.projects = []
        for i, p in enumerate(projects):
            x = 120 + i * (CW - 420) / max(n - 1, 1)
            up = i % 2 == 0
            y = trunk_y(x) + (-1 if up else 1) * 44
            f = Item("folder", p["name"] + "/", x, y)
            self.items.append(f)
            self.projects.append(dict(data=p, folder=f, up=up))
        # extra top-level files float near little twigs off the trunk
        self.root_files = []
        for k, name in enumerate(cfg.get("root_files", [])):
            it = self._float_near(self.trunk, "file", name, self.home, (0.42, 0.62), side=1 if k % 2 else -1)
            if it:
                self.root_files.append(it)

        # each project: a limb out of its folder, then a limb out of one subfolder
        for pr in self.projects:
            d = pr["data"]
            f = pr["folder"]
            pr["limb"], pr["view"] = self._limb_from(f, pr["up"], 580, steep=True)
            pr["kids"], pr["sub"] = self._fill(pr["limb"], d["items"], pr["view"], pr["up"], d.get("sub"))
            pr["sub_limb"] = pr["sub_view"] = None
            pr["sub_kids"] = []
            if pr["sub"] is not None:
                pr["sub_limb"], pr["sub_view"] = self._limb_from(pr["sub"], pr["up"], 480, steep=False)
                pr["sub_kids"], _ = self._fill(pr["sub_limb"], d.get("sub_items", []), pr["sub_view"], pr["up"], None)

    # -- helpers ---------------------------------------------------------
    def _add_branch(self, b):
        self.branches.append(b)
        for s in range(0, b.L, 6):
            x, y, _ = b.at(s)
            self.samples.append((x, y, b.width(s) / 2))

    def _clear(self, box, pad=18):
        for x, y, hw in self.samples:
            if box_dist(box, x, y) < hw + pad:
                return False
        return not any(overlap(box, it.box, 16) for it in self.items)

    @staticmethod
    def _in_view(box, view, margin=16):
        return (box[0] > view[0] - CW / 2 + margin and box[2] < view[0] + CW / 2 - margin
                and box[1] > view[1] - CH / 2 + margin and box[3] < view[1] + CH / 2 - margin)

    def _limb_from(self, folder, up, length, steep):
        """Grows a limb out of a folder icon (up-right or down-right), choosing the
        variant that stays clear of existing branches, and the camera view for it.
        Top-level limbs grow steeper so neighbouring projects get their own diagonal band."""
        rng = self.rng
        best = None
        sg = -1 if up else 1
        h0, h1 = ((1.2, 1.4), (0.25, 0.5)) if steep else ((0.9, 1.2), (0.0, 0.3))
        for attempt in range(60):
            L = length * rng.uniform(0.85, 1.05)
            pts = grow(rng, (folder.cx, folder.cy), sg * rng.uniform(*h0), L,
                       sg * rng.uniform(*h1), pull=rng.uniform(0.012, 0.02), wobble=rng.uniform(0.003, 0.005))
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            oversize = max(0, max(xs) - min(xs) - (CW - 300)) + max(0, max(ys) - min(ys) - (CH - 170))
            clash = sum(1 for x, y, _ in pts[60::10] for sx, sy, hw in self.samples
                        if abs(sx - x) < 40 and abs(sy - y) < 40)
            score = clash + oversize
            if best is None or score < best[0]:
                best = (score, pts)
            if score == 0:
                break
        pts = best[1]
        limb = Branch(pts, 10, 3, "limb", 1.0)
        self._add_branch(limb)
        folder.base = True
        # frame the limb, keeping the folder comfortably inside the view
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        vx = (min(xs) + max(xs)) / 2 + 40
        vy = (min(ys) + max(ys)) / 2
        vx = min(max(vx, folder.cx + 90 - CW / 2 + 60), folder.cx - 90 + CW / 2 - 60)
        vy = min(max(vy, folder.cy + 70 - CH / 2), folder.cy - 70 + CH / 2)
        self._decorate(limb, up)
        return limb, (vx, vy)

    def _decorate(self, limb, up):
        """A fork two-thirds along, a small Y at the tip, and a few forward-leaning twigs."""
        rng = self.rng
        sg = -1 if up else 1
        L = limb.L
        s = int(L * rng.uniform(0.55, 0.7))
        x, y, th = limb.at(s)
        fork = Branch(grow(rng, (x, y), th + sg * rng.uniform(0.35, 0.55), L * rng.uniform(0.28, 0.4),
                           th + sg * 0.25, pull=0.01, wobble=0.002), limb.width(s) * 0.7, 2, "twig", 0.6)
        fork.parent, fork.parent_s = limb, s
        self._add_branch(fork)
        for b in (limb, fork):
            x, y, th = b.at(b.L - 1)
            for da in (-0.45, 0.4):
                tw = Branch(grow(rng, (x, y), th + da, rng.uniform(26, 60), th + da * 0.5, pull=0.02, wobble=0.0),
                            2, 2, "twig", 0.0)
                tw.parent, tw.parent_s = b, b.L - 1
                self._add_branch(tw)
        for _ in range(rng.randint(2, 3)):
            s = int(L * rng.uniform(0.25, 0.85))
            x, y, th = limb.at(s)
            da = rng.choice([-1, 1]) * rng.uniform(0.35, 0.75)
            tw = Branch(grow(rng, (x, y), th + da, rng.uniform(24, 64), th + da * 0.4, pull=0.02, wobble=0.0),
                        2, 2, "twig", 0.0)
            tw.parent, tw.parent_s = limb, s
            self._add_branch(tw)

    def _float_near(self, branch, kind, name, view, s_range, side, label_below=False):
        """Floats an item beside a branch, 45-110 px off it, inside `view`."""
        rng = self.rng
        best = None
        for attempt in range(260):
            s = rng.uniform(*s_range) * branch.L
            x, y, th = branch.at(s)
            sd = side if attempt < 80 else rng.choice([-1, 1])
            nx, ny = -math.sin(th) * sd, math.cos(th) * sd
            d = rng.uniform(42, 120 if attempt < 160 else 170)
            it = Item(kind, name, x + nx * d + (30 if not label_below else 0), y + ny * d, label_below)
            if not (self._in_view(it.box, view) and self._clear(it.box, 18 if attempt < 160 else 10)):
                continue
            spread = min([math.hypot(it.cx - q.cx, it.cy - q.cy) for q in self.items] or [999])
            if best is None or spread > best[0]:
                best = (spread, it, s)
        if best is None:
            return None
        _, it, s = best
        it.attach = (branch, s)
        self.items.append(it)
        # a short twig reaching toward it (stopping short; nothing touches the icon)
        x, y, th = branch.at(s)
        dist = math.hypot(it.cx - x, it.cy - y)
        if dist > 60 and self.rng.random() < 0.7:
            ang = math.atan2(it.cy - y, it.cx - x)
            tw = Branch(grow(self.rng, (x, y), (th + ang) / 2 if abs(th - ang) < 2 else ang, dist - 34, ang,
                             pull=0.03, wobble=0.0), 2, 2, "twig", 0.0)
            tw.parent, tw.parent_s = branch, s
            self._add_branch(tw)
        return it

    def _fill(self, limb, entries, view, up, sub_name):
        """Places a folder's contents around its limb. The subfolder that will be
        opened next goes on the outer side, two-thirds along, with room for its limb."""
        kids, sub = [], None
        entries = entries[: self.max_files]
        outer = -1 if up else 1
        if sub_name and any(n == sub_name + "/" for _, n in entries):
            sub = self._float_near(limb, "folder", sub_name + "/", view, (0.55, 0.85), side=outer)
            if sub:
                kids.append(sub)
        for k, (kind, name) in enumerate(entries):
            if sub and name == sub.name:
                continue
            it = self._float_near(limb, kind, name, view, (0.12, 1.0), side=1 if k % 2 else -1,
                                  label_below=(kind == "folder"))
            if it:
                kids.append(it)
        kids.sort(key=lambda it: it.attach[1])
        return kids, sub

    # -- pixels ----------------------------------------------------------
    def rasterise(self):
        cells = {}
        clear = []
        for it in self.items:
            clear.append(it.label_box)
            if not it.base:
                clear.append((it.ix - 4, it.iy - 4, it.ix + it.w + 4, it.iy + it.h + 4))

        def blocked(x, y):
            return any(c[0] <= x <= c[2] and c[1] <= y <= c[3] for c in clear)

        def put(cx, cy, born, col, layer):
            old = cells.get((cx, cy))
            if old is None or layer > old[2]:
                cells[(cx, cy)] = (born, col, layer)
            elif layer == old[2] and born < old[0]:
                cells[(cx, cy)] = (born, old[1], layer)

        for b in self.branches:
            seed = len(b.pts) * 31 + int(b.pts[0][0]) * 7 + int(b.pts[0][1])
            for s in range(b.L):
                x, y, th = b.at(s)
                born = b.time(s)
                w = b.width(s)
                r = w / 2
                tx, ty = math.cos(th), math.sin(th)
                nx, ny = -ty, tx
                if ny < 0:
                    nx, ny = -nx, -ny                   # normal points down the screen
                if w <= 2.5:
                    # dotted single-cell line
                    cx, cy = math.floor(x / P), math.floor(y / P)
                    if hash01(cx, cy, seed) < 0.62 and not blocked(x, y):
                        put(cx, cy, born, pick(BARK_CORE, hash01(cx, cy, 5)), 1)
                    continue
                reach = r + P
                for cy in range(math.floor((y - reach) / P), math.floor((y + reach) / P) + 1):
                    for cx in range(math.floor((x - reach) / P), math.floor((x + reach) / P) + 1):
                        px, py = cx * P + P / 2 - x, cy * P + P / 2 - y
                        along = px * tx + py * ty
                        if abs(along) > P * 0.55:
                            continue
                        perp = px * nx + py * ny
                        if abs(perp) > r + P * 0.35:
                            continue
                        if abs(perp) > r - P * 0.4 and hash01(cx, cy, 11) > 0.55:
                            continue                    # ragged, dithered edge
                        if blocked(cx * P, cy * P):
                            continue
                        u = hash01(cx, cy, 3)
                        rel = perp / max(r, 1)
                        if rel < -0.3:
                            col = pick(BARK_TOP, u)
                        elif rel > 0.35:
                            col = pick(BARK_UNDER, u)
                        else:
                            col = pick(BARK_CORE, u)
                        put(cx, cy, born, col, 1)

            # a lime cell at twig tips
            if b.kind == "twig":
                x, y, _ = b.at(b.L - 1)
                put(math.floor(x / P), math.floor(y / P), b.time(b.L - 1) + 0.25, TIP[seed % 3], 2)
            # moss: dense near the base, fading out along the branch, in patches
            if b.moss <= 0:
                continue
            rng = random.Random(seed)
            ph = rng.uniform(0, 100)
            for s in range(0, b.L, 3):
                x, y, th = b.at(s)
                r = b.width(s) / 2
                f = s / b.L
                if b.kind == "trunk":
                    base = 0.42 * max(0.1, min(1.0, 1.05 - (x + 200) / (CW + 200)))
                else:
                    base = 0.75 * math.exp(-f / 0.3) + 0.08
                patch = 0.5 + 0.5 * math.sin(s / 37 + ph) * math.sin(s / 13 + ph * 1.7)
                if rng.random() > b.moss * base * max(0.0, patch * 1.4 - 0.2):
                    continue
                tx, ty = math.cos(th), math.sin(th)
                nx, ny = -ty, tx
                if ny < 0:
                    nx, ny = -nx, -ny
                if rng.random() < 0.75:                 # mostly on the upper side
                    off = -(r * 0.6 + rng.uniform(0, 1.8) * P)
                else:
                    off = r * 0.4 + rng.uniform(0, 1.0) * P
                mx = x + nx * off + tx * rng.uniform(-P, P)
                my = y + ny * off + ty * rng.uniform(-P, P)
                rad = rng.uniform(0.8, 2.0) * P * ((1.0 + 0.9 * (1 - f)) if b.kind != "trunk" else 1.2)
                born = b.time(s) + 0.35 + rng.uniform(0, 0.5)
                for cy in range(math.floor((my - rad * 1.6) / P), math.floor((my + rad * 1.6) / P) + 1):
                    for cx in range(math.floor((mx - rad * 1.6) / P), math.floor((mx + rad * 1.6) / P) + 1):
                        px, py = cx * P + P / 2 - mx, cy * P + P / 2 - my
                        a, c = px * tx + py * ty, px * nx + py * ny
                        if (a / (rad * 1.5)) ** 2 + (c / rad) ** 2 > 1 or hash01(cx, cy, 17) < 0.28:
                            continue
                        if blocked(cx * P, cy * P):
                            continue
                        put(cx, cy, born, pick(MOSS, hash01(cx, cy, 23)), 2)

        self.cells = sorted(((cx * P, cy * P, born, col, layer) for (cx, cy), (born, col, layer) in cells.items()),
                            key=lambda c: c[0])
        self.cell_x = [c[0] for c in self.cells]


# ---------------- drawing ----------------
def mix(c, bg, a):
    return tuple(int(bg[i] + (c[i] - bg[i]) * a) for i in range(3))


def folder_icon(d, x, y, s, stroke, open_=False):
    w, h = 34 * s, 28 * s
    if open_:
        lw = 3
        d.rounded_rectangle([x, y, x + 13 * s, y + 9 * s], 3, fill=WIN, outline=stroke, width=lw)
        d.rounded_rectangle([x, y + 5 * s, x + w - 5 * s, y + h], 3, fill=WIN, outline=stroke, width=lw)
        d.polygon([(x + 5 * s, y + 11 * s), (x + w + 1 * s, y + 11 * s), (x + w - 5 * s, y + h), (x - 1 * s, y + h)],
                  fill=WIN, outline=stroke, width=lw)
        return
    d.rounded_rectangle([x, y, x + 13 * s, y + 9 * s], 3, fill=WIN, outline=stroke, width=2)
    d.rounded_rectangle([x, y + 5 * s, x + w, y + h], 4, fill=WIN, outline=stroke, width=2)


def file_icon(d, x, y, s, stroke, lines, bold=False):
    x += 6 * s
    w, h, f = 22 * s, 28 * s, 7 * s
    lw = 3 if bold else 2
    d.polygon([(x, y), (x + w - f, y), (x + w, y + f), (x + w, y + h), (x, y + h)], fill=WIN)
    d.line([(x + w - f, y), (x, y), (x, y + h), (x + w, y + h), (x + w, y + f), (x + w - f, y),
            (x + w - f, y + f), (x + w, y + f)], fill=stroke, width=lw, joint="curve")
    if lines:
        for k in range(4):
            d.line([(x + 4 * s, y + (11 + k * 4) * s), (x + w - 4 * s, y + (11 + k * 4) * s)], fill=stroke, width=1)


def chrome(d, title, back, items_text):
    d.rounded_rectangle([WX0 + 4, WY0 + 8, WX1 + 4, WY1 + 12], 16, fill=(8, 10, 14))
    d.rounded_rectangle([WX0, WY0, WX1, WY1], 14, fill=WIN, outline=BORDER, width=2)
    d.line([WX0, WY0 + TITLE_H, WX1, WY0 + TITLE_H], fill=BORDER, width=2)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        d.ellipse([WX0 + 18 + i * 21, WY0 + 17, WX0 + 30 + i * 21, WY0 + 29], fill=c)
    d.text((WX0 + 98, WY0 + 23), "‹", font=font(22, "Medium"), fill=TEXT if back else BORDER, anchor="mm")
    cx = (WX0 + WX1) / 2
    tw = text_w(title, TITLE)
    hx = cx - (tw + 28) / 2
    folder_icon(d, hx, WY0 + 16, 0.55, TEXT)
    d.text((hx + 28, WY0 + 23), title, font=TITLE, fill=TEXT_HI, anchor="lm")
    d.text((WX1 - 52, WY0 + 23), "»", font=TITLE, fill=TEXT, anchor="mm")
    d.ellipse([WX1 - 31, WY0 + 15, WX1 - 20, WY0 + 26], outline=TEXT, width=2)
    d.line([WX1 - 22, WY0 + 25, WX1 - 17, WY0 + 30], fill=TEXT, width=2)
    d.text((cx, WY1 - FOOT_H / 2), items_text, font=SMALL, fill=TEXT_DIM, anchor="mm")


# ---------------- timeline ----------------
class Movie:
    def __init__(self, cfg, projects):
        self.title = cfg.get("title", cfg["user"])
        self.world = World(projects, cfg)
        self.keys = []                 # camera (t, x, y)
        self.lit = []                  # [t0, t1, item] shown highlighted
        self.scenes = []               # (t0, title, back, n_items)
        self._script()
        self.world.rasterise()

    def _grow(self, b, t0, dur):
        b.born0, b.dur = t0, dur
        for c in self.world.branches:            # twigs off this branch start when growth reaches them
            if getattr(c, "parent", None) is b:
                self._grow(c, b.time(c.parent_s), max(0.25, dur * c.L / b.L * 1.2))

    @staticmethod
    def _appear(items):
        for it in items:
            br, s = it.attach
            it.born = br.time(s) + 0.15

    def _visit(self, t, folder, limb, kids, view, from_view, path):
        """Light the folder, grow its limb while the camera pans, name a few items."""
        self.lit.append([t, None, folder])
        self.scenes.append((t + 0.35, path, True, len(kids)))
        t += 0.35
        self._grow(limb, t, 1.0)
        self._appear(kids)
        self.keys.append((t + 0.1, *from_view))
        self.keys.append((t + 0.1 + 1.4, *view))
        t += 1.0 + 0.6
        shown = ([k for k in kids if k.kind == "file"] + [k for k in kids if k.kind == "folder" and not k.base])[:2]
        for it in sorted(shown, key=lambda k: k.attach[1]):
            self.lit.append([t, t + 0.4, it])
            t += 0.45
        return t + 0.1

    def _script(self):
        wd = self.world
        home = wd.home
        tr = wd.trunk
        x0, x1 = -60, CW + 60
        tr.time_fn = lambda x: 0.3 + 1.5 * min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        for c in wd.branches:                    # twigs off the trunk
            if getattr(c, "parent", None) is tr:
                self._grow(c, tr.time(c.parent_s), 0.5)
        for pr in wd.projects:
            pr["folder"].born = tr.time_fn(pr["folder"].cx) + 0.1
        self._appear(wd.root_files)
        n_root = len(wd.projects) + len(wd.root_files)
        self.scenes.append((0.0, self.title, False, n_root))
        self.keys.append((0.0, *home))
        t = 0.3 + 1.5 + 0.7
        for pr in wd.projects:
            self.keys.append((t, *home))
            name = pr["data"]["name"]
            t = self._visit(t, pr["folder"], pr["limb"], pr["kids"], pr["view"], home, f"{self.title} / {name}")
            last = pr["view"]
            if pr["sub"] is not None:
                self.keys.append((t, *pr["view"]))
                t = self._visit(t, pr["sub"], pr["sub_limb"], pr["sub_kids"], pr["sub_view"], pr["view"],
                                f"{name} / {pr['sub'].name.rstrip('/')}")
                last = pr["sub_view"]
            # glide back to the trunk
            self.keys.append((t, *last))
            self.scenes.append((t + 0.5, self.title, False, n_root))
            t += 1.4
            self.keys.append((t, *home))
            for entry in self.lit:
                if entry[1] is None:
                    entry[1] = t
            t += 0.3
        self.fade = (t + 0.3, t + 1.0)
        self.duration = t + 1.3
        self.keys.append((self.duration, *home))
        self.keys.sort()

    def camera(self, t):
        ks = self.keys
        if t <= ks[0][0]:
            return ks[0][1:]
        for (t0, x0, y0), (t1, x1, y1) in zip(ks, ks[1:]):
            if t0 <= t <= t1:
                u = ease((t - t0) / (t1 - t0)) if t1 > t0 else 1
                return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
        return ks[-1][1:]

    def frame(self, t):
        wd = self.world
        img = Image.new("RGB", (W, H), PAGE)
        d = ImageDraw.Draw(img)
        cx, cy = self.camera(t)
        ox, oy = CW / 2 - cx, CH / 2 - cy
        content = Image.new("RGB", (CW, CH), WIN)
        cd = ImageDraw.Draw(content)
        fade = 1.0 - ease((t - self.fade[0]) / (self.fade[1] - self.fade[0]))

        lo = bisect.bisect_left(wd.cell_x, cx - CW / 2 - P)
        hi = bisect.bisect_right(wd.cell_x, cx + CW / 2 + P)
        for x, y, born, col, layer in wd.cells[lo:hi]:
            if born > t:
                continue
            X, Y = round(x + ox), round(y + oy)
            if -P <= Y <= CH:
                a = min(1.0, (t - born) / 0.12) * fade        # cells pop in quickly, not instantly
                cd.rectangle([X, Y, X + DOT - 1, Y + DOT - 1], fill=mix(col, WIN, a) if a < 1 else col)

        lit_now = {id(it) for t0, t1, it in self.lit if t0 <= t < (t1 if t1 is not None else 1e9)}
        for it in wd.items:
            if it.born > t:
                continue
            X0, Y0 = it.ix + ox, it.iy + oy
            if it.box[2] + ox < 0 or X0 > CW or it.box[3] + oy < 0 or Y0 > CH:
                continue
            a = min(1.0, (t - it.born) / 0.3) * fade
            on = id(it) in lit_now
            stroke = mix(TEXT_HI if on else TEXT, WIN, a)
            if it.kind == "folder":
                folder_icon(cd, X0, Y0, ICON, stroke, open_=on)
            else:
                file_icon(cd, X0, Y0, ICON, stroke, it.name.lower().endswith(TEXT_FILES), bold=on)
            cd.text((it.lx + ox, it.ly + oy), it.name, font=LABEL, fill=stroke, anchor=it.anchor)

        scene = [s for s in self.scenes if s[0] <= t][-1]
        n = scene[3] if fade > 0.5 else 0
        chrome(d, scene[1], scene[2], f"{n} item{'s' if n != 1 else ''}")
        img.paste(content, (CX0, CY0))
        d.line([WX0, WY1 - FOOT_H, WX1, WY1 - FOOT_H], fill=BORDER, width=1)
        return img


# ---------------- README links ----------------
def update_readme(cfg, projects):
    path = os.path.join(ROOT, cfg.get("readme", "README.md"))
    if not os.path.exists(path):
        return
    text = open(path, encoding="utf-8").read()
    links = " · ".join(f"[{p['name']}](https://github.com/{cfg['user']}/{p['name']})" for p in projects)
    block = f"<!-- tree:projects -->\n{links}\n<!-- /tree:projects -->"
    new = re.sub(r"<!-- tree:projects -->.*?<!-- /tree:projects -->", block, text, flags=re.S)
    if new != text:
        open(path, "w", encoding="utf-8", newline="\n").write(new)
        print("  README project links updated")


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    cache = os.path.join(HERE, ".cache.json")
    cached = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else None
    if "--offline" in sys.argv and cached and all("sub" in p for p in cached):
        projects = cached
    else:
        projects = fetch(cfg)
        json.dump(projects, open(cache, "w", encoding="utf-8"), indent=1)
    projects = projects[: cfg.get("max_projects", 4)]
    print("projects:", ", ".join(f"{p['name']} (+{p['sub']})" for p in projects))
    movie = Movie(cfg, projects)
    print(f"loop: {movie.duration:.1f}s, {len(movie.world.cells)} cells")

    if "--still" in sys.argv:
        i = sys.argv.index("--still")
        t = float(sys.argv[i + 2]) if len(sys.argv) > i + 2 and not sys.argv[i + 2].startswith("--") else 3.0
        movie.frame(t).save(sys.argv[i + 1])
        return
    if "--sheet" in sys.argv:
        out = sys.argv[sys.argv.index("--sheet") + 1]
        times = [movie.duration * k / 12 for k in range(12)]
        sheet = Image.new("RGB", (640 * 3, 380 * 4))
        for k, t in enumerate(times):
            sheet.paste(movie.frame(t).resize((640, 380)), ((k % 3) * 640, (k // 3) * 380))
        sheet.save(out)
        return

    frames = [movie.frame(i / FPS) for i in range(int(movie.duration * FPS))]
    out = os.path.join(ROOT, cfg.get("output", "tree.webp"))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0,
                   quality=70, method=6)
    print(f"saved {out} ({os.path.getsize(out) / 1e6:.1f} MB, {len(frames)} frames)")
    update_readme(cfg, projects)


if __name__ == "__main__":
    main()
