#!/usr/bin/env python3
"""Render a GitHub contribution calendar as Sooz slashing her way across it.

Everything rides one master timeline that repeats indefinitely, so the loop is
seamless and no element needs its own `begin` offset: she enters from the left,
hops to reach the high rows, slashes every week that has contributions, the
cells burst into coins, and she exits right.

Usage:  python3 gen.py [contrib.json] [-o out]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# --- grid geometry --------------------------------------------------------
CELL, GAP = 14, 4
PITCH = CELL + GAP
DAYS = 7
MARGIN_X = 60
GRAPH_Y = 40

# --- pacing ---------------------------------------------------------------
DUR = 9.0
# Her stride must match her ground speed or she looks like she is skating, so
# the frame rate falls out of the speed instead of being pinned independently.
STRIDE = 41.0

# --- jump, lifted from the game rather than invented -----------------------
# src/game/entities.js SOOZ: GRAV_UP 0.42, GRAV_DOWN 0.68, JUMP -6.6. The
# asymmetry is the whole feel; she floats up and drops fast. A symmetric
# parabola reads as moon gravity next to real gameplay.
GRAV_UP, GRAV_DOWN, JUMP_V = 0.42, 0.68, -6.6
TICK = 1.0 / 60          # the game's own tick, so the curve matches 1:1
V_APEX, V_FALL1, V_FALL2 = -1.6, 1.2, 4.2   # air-frame thresholds, entities.js

MAX_LIFT = 76            # ceiling on hop height
MIN_LIFT = 30            # lower than this she reaches from the ground
BLADE_Y = 34             # blade height, measured down from the top of her frame
GROUND_MIN = 0.22        # forced seconds grounded between hops, so she visibly runs
SWORD = 96               # x offset inside her frame where the blade lands

# --- event timings, authored against a 20s loop and scaled to DUR ----------
_S = DUR / 20.0
POP_T1, POP_T2 = 0.10 * _S, 0.26 * _S
ARC_T1, ARC_T2 = 0.09 * _S, 0.28 * _S
COIN_DELAY, COIN_FADE, COIN_END = 0.05 * _S, 0.95 * _S, 1.15 * _S
OUTRO = 1.2 * _S

GOLD, GOLD_DK, PINK = "#f9c22b", "#f79617", "#f04f78"
LEVEL = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
         "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

THEMES = {
    "dark": dict(bg="#17121f", ground="#2b2334", groundEdge="#3d3350",
                 text="#8b949e", title="#e6edf3", gold=GOLD,
                 lv=["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"]),
    "light": dict(bg="#f6f2ef", ground="#e2d9d2", groundEdge="#cdbfb4",
                  text="#6e7781", title="#1f2328", gold=GOLD_DK,
                  lv=["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]),
}


def num(x):
    """Trim a float to the shortest form SVG needs."""
    return f"{x:.4f}".rstrip("0").rstrip(".")


def keytimes(*ts):
    """Clamp to [0,1] and force non-decreasing.

    SMIL drops an animation outright if keyTimes are out of order or out of
    range, which fails silently and is near-impossible to spot in a 400 KB file.
    Every keyTimes list in this module goes through here.
    """
    out, prev = [], 0.0
    for t in ts:
        prev = max(prev, min(float(t), 1.0))
        out.append(num(prev))
    return ";".join(out)


# --- jump curve -----------------------------------------------------------

def _jump_curve():
    """Integrate the game's own jump once. Returns [(t, height, vy)]."""
    vy, y, t = JUMP_V, 0.0, 0.0
    pts = [(0.0, 0.0, vy)]
    while True:
        vy += GRAV_UP if vy < 0 else GRAV_DOWN
        y += vy
        t += TICK
        pts.append((t, -y, vy))
        if y >= 0:
            return pts


JUMP_PTS = _jump_curve()
JUMP_AIR = JUMP_PTS[-1][0]                        # total airtime, ~0.47s
JUMP_PEAK = max(h for _, h, _ in JUMP_PTS)
JUMP_RISE = max(JUMP_PTS, key=lambda p: p[1])[0]  # takeoff to apex


class Layout:
    """Canvas metrics. Week count is data, not a constant: a truncated calendar
    would otherwise render at 53-week width with a dead column on the right."""

    def __init__(self, weeks, frame_w, frame_h):
        self.weeks = weeks
        self.graph_w = weeks * PITCH - GAP
        self.graph_h = DAYS * PITCH - GAP
        self.w = self.graph_w + MARGIN_X * 2
        self.ground_y = GRAPH_Y + self.graph_h + 14
        self.h = self.ground_y + 26
        self.sprite_y = self.ground_y - frame_h + 4

        self.x_start, self.x_end = -frame_w - 20, self.w + 20
        self.speed = (self.x_end - self.x_start) / DUR
        self.fps = max(1, round(8 * self.speed / STRIDE))
        self.nf = max(1, round(DUR * self.fps))
        # Exactly three frames per hit, one per combo pose. Derived from fps
        # because with ~49 target weeks the hits land every ~0.18s and any
        # wider window swallows the run and air frames whole.
        self.slash_window = 1.5 / self.fps

    def cell_xy(self, w, d):
        return MARGIN_X + w * PITCH, GRAPH_Y + d * PITCH

    def hit_time(self, w):
        """When the blade reaches the centre of week w."""
        col = MARGIN_X + w * PITCH + CELL / 2
        return (col - SWORD - self.x_start) / (self.x_end - self.x_start) * DUR


def load_sprite():
    path = os.path.join(HERE, "sooz-strip.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"missing {path}; run prep_sprites.py first")


def load_calendar(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"no calendar at {path}; see README.md for how to fetch one")
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON: {e}")
    try:
        cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    except (KeyError, TypeError):
        sys.exit(f"{path} is not a contribution calendar response")

    unknown = set()
    cells = []
    for wi, week in enumerate(cal.get("weeks", [])):
        for day in week.get("contributionDays", []):
            raw = day.get("contributionLevel")
            if raw not in LEVEL:
                unknown.add(raw)
            lv = LEVEL.get(raw, 0)
            if lv:
                cells.append(dict(w=wi, d=day["weekday"], lv=lv, date=day["date"]))
    if unknown:
        print(f"warning: unrecognised contribution levels {sorted(unknown)}, "
              f"treated as empty", file=sys.stderr)
    return cal, cells


def build(theme_name, cal, cells, sp, lay):
    """Emit one themed SVG as a string."""
    T = THEMES[theme_name]
    fw, fh = sp["frameW"], sp["frameH"]
    names = sp["names"]
    run = [names.index(f"run{i}") for i in range(8)]
    combo = [names.index(n) for n in ("thrust", "arcslash", "riposte")]
    flourish = names.index("flourish")
    rise, fall1, fall2, land = (names.index(n) for n in ("rise", "fall1", "fall2", "land"))

    total = cal.get("totalContributions", 0)
    hits = {w: lay.hit_time(w) for w in sorted({c["w"] for c in cells})}
    tops = {w: min(c["d"] for c in cells if c["w"] == w) for w in hits}

    out = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
      f'width="{lay.w}" height="{lay.h}" viewBox="0 0 {lay.w} {lay.h}" role="img" '
      f'aria-label="Slay Rat slashing a GitHub contribution graph, '
      f'{total} contributions in the last year">')
    a(f'<title>Slay Rat vs. {total:,} contributions</title>')

    a('<defs>')
    a('<linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">'
      f'<stop offset="0" stop-color="#ffe07a"/><stop offset="1" stop-color="{GOLD_DK}"/>'
      '</linearGradient>')
    # The spin animates each ellipse's own rx. An <animate> placed directly in
    # the <g> would target the <g>, which has no rx, and silently do nothing.
    a(f'<g id="coin">'
      f'<ellipse rx="5" ry="5" fill="url(#cg)" stroke="{GOLD_DK}" stroke-width="1">'
      f'<animate attributeName="rx" values="5;1.2;5" dur=".45s" repeatCount="indefinite"/>'
      f'</ellipse>'
      f'<ellipse rx="1.6" ry="3" fill="#fff3c4" opacity=".85">'
      f'<animate attributeName="rx" values="1.6;0.4;1.6" dur=".45s" repeatCount="indefinite"/>'
      f'</ellipse></g>')
    a(f'<path id="arc" d="M0,-30 A34,34 0 0 1 0,30 A46,46 0 0 0 0,-30 Z" fill="{PINK}"/>')
    a(f'<image id="sheet" width="{fw * len(names)}" height="{fh}" '
      f'style="image-rendering:pixelated" xlink:href="data:image/png;base64,{sp["b64"]}"/>')
    a(f'<clipPath id="fclip"><rect width="{fw}" height="{fh}"/></clipPath>')
    a('</defs>')

    a(f'<rect width="{lay.w}" height="{lay.h}" rx="10" fill="{T["bg"]}"/>')

    # Month labels, keyed on (year, month): a rolling 12-month calendar spans
    # 13 months and the first and last share a month number.
    seen = set()
    for wi, week in enumerate(cal.get("weeks", [])):
        days = week.get("contributionDays")
        if not days:
            continue
        year, month, dom = (int(v) for v in days[0]["date"].split("-"))
        if dom <= 7 and (year, month) not in seen:
            seen.add((year, month))
            a(f'<text x="{MARGIN_X + wi * PITCH}" y="{GRAPH_Y - 10}" '
              f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
              f'font-size="11" fill="{T["text"]}">{MONTHS[month - 1]}</text>')

    # Static grid, so empty days still read as a calendar.
    a('<g>')
    for wi, week in enumerate(cal.get("weeks", [])):
        for day in week.get("contributionDays", []):
            if LEVEL.get(day.get("contributionLevel"), 0):
                continue
            x, y = lay.cell_xy(wi, day["weekday"])
            a(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" '
              f'fill="{T["lv"][0]}"/>')
    a('</g>')

    # Destructible cells.
    a('<g>')
    for c in cells:
        x, y = lay.cell_xy(c["w"], c["d"])
        th = hits[c["w"]]
        kt = keytimes(0, th / DUR, (th + POP_T1) / DUR, (th + POP_T2) / DUR, 1)
        a(f'<g transform="translate({num(x + CELL / 2)},{num(y + CELL / 2)})">'
          f'<rect x="{-CELL / 2}" y="{-CELL / 2}" width="{CELL}" height="{CELL}" rx="3" '
          f'fill="{T["lv"][c["lv"]]}">'
          f'<animateTransform attributeName="transform" type="scale" '
          f'values="1;1;1.65;0;0" keyTimes="{kt}" dur="{num(DUR)}s" '
          f'calcMode="linear" repeatCount="indefinite"/></rect></g>')
    a('</g>')

    # Ground, before the coins so they fly in front of it.
    a(f'<rect x="0" y="{lay.ground_y}" width="{lay.w}" height="{lay.h - lay.ground_y}" '
      f'fill="{T["ground"]}"/>')
    a(f'<rect x="0" y="{lay.ground_y}" width="{lay.w}" height="2" fill="{T["groundEdge"]}"/>')

    # Coins. keyPoints="0;0;1;1" holds each coin at its start, flies it during
    # its own window, then holds it at the end, which is what lets every coin
    # share the single global timeline.
    a('<g>')
    for i, c in enumerate(cells):
        x, y = lay.cell_xy(c["w"], c["d"])
        cx, cy = x + CELL / 2, y + CELL / 2
        th = hits[c["w"]]
        for k in range(min(c["lv"] + 1, 3)):
            spread = (k - c["lv"] / 2) * 26 + ((i * 37 + k * 53) % 17) - 8
            rise_px = 70 + ((i * 29 + k * 41) % 38)
            t0 = (th + COIN_DELAY) / DUR
            tf = (th + COIN_FADE) / DUR
            t1 = (th + COIN_END) / DUR
            a(f'<use xlink:href="#coin" opacity="0">'
              f'<animateMotion dur="{num(DUR)}s" repeatCount="indefinite" calcMode="linear" '
              f'keyTimes="{keytimes(0, t0, t1, 1)}" keyPoints="0;0;1;1" '
              f'path="M{num(cx)},{num(cy)} q{num(spread)},{num(-rise_px)} '
              f'{num(spread * 2.3)},{num(-rise_px * 0.55)}"/>'
              f'<animate attributeName="opacity" dur="{num(DUR)}s" repeatCount="indefinite" '
              f'values="0;0;1;1;0;0" keyTimes="{keytimes(0, t0, t0 + 0.004, tf, t1, 1)}"/>'
              f'</use>')
    a('</g>')

    # Slash arcs, flashed at each hit.
    a('<g>')
    for w, th in hits.items():
        col = MARGIN_X + w * PITCH + CELL / 2
        mid = GRAPH_Y + (tops[w] + max(c["d"] for c in cells if c["w"] == w)) / 2 * PITCH + CELL / 2
        kt = keytimes(0, th / DUR, (th + ARC_T1) / DUR, (th + ARC_T2) / DUR, 1)
        a(f'<use xlink:href="#arc" transform="translate({num(col)},{num(mid)}) scale(1.5)" '
          f'opacity="0"><animate attributeName="opacity" dur="{num(DUR)}s" '
          f'repeatCount="indefinite" values="0;0;.95;0;0" keyTimes="{kt}"/></use>')
    a('</g>')

    # --- Sooz -------------------------------------------------------------
    # One hop per high week, apex timed onto the hit. Hops may not overlap:
    # hits land every ~0.18s against ~0.47s of airtime, so without the guard
    # she merges into a permanent hover and never touches the ground.
    jumps, busy_until = [], -1e9
    for w in sorted(hits, key=hits.get):
        th = hits[w]
        lift = min(MAX_LIFT, (lay.sprite_y + BLADE_Y)
                   - (GRAPH_Y + tops[w] * PITCH + CELL / 2))
        if lift < MIN_LIFT or th - JUMP_RISE < busy_until:
            continue
        jumps.append((th, lift))
        busy_until = th - JUMP_RISE + JUMP_AIR + GROUND_MIN

    def air_at(t):
        """(height, vy) for whichever hop is active at t; vy is None on the ground."""
        for th, lift in jumps:
            u = t - th + JUMP_RISE
            if 0 <= u <= JUMP_AIR:
                i = min(int(u / TICK), len(JUMP_PTS) - 2)
                k = (u - JUMP_PTS[i][0]) / TICK
                h = JUMP_PTS[i][1] + (JUMP_PTS[i + 1][1] - JUMP_PTS[i][1]) * k
                return h / JUMP_PEAK * lift, JUMP_PTS[i][2]
        return 0.0, None

    last_hit = max(hits.values(), default=0.0)

    # The position track needs NF+1 samples: with no explicit keyTimes, SMIL
    # spreads N values over N-1 intervals, so NF samples would run the walk
    # 1/NF fast and desync it from the discrete NF-slot frame track.
    pos = []
    for f in range(lay.nf + 1):
        t = f / lay.fps
        x = lay.x_start + (lay.x_end - lay.x_start) * t / DUR
        pos.append(f"{num(x)},{num(lay.sprite_y - air_at(t)[0])}")

    frames, run_phase = [], 0
    for f in range(lay.nf):
        t = f / lay.fps
        _, vy = air_at(t)
        dt = min((t - th for th in hits.values()), key=abs, default=1e9)
        landing = vy is None and air_at(t - 1.0 / lay.fps)[1] is not None

        if t > last_hit + OUTRO:
            frames.append(flourish)
        elif landing:
            frames.append(land)             # outranks the slash: one frame, and
                                            # without it a hop has no touchdown
        elif vy is not None and vy < V_APEX:
            frames.append(rise)             # climbing: the hop must read as a hop
        elif vy is not None and vy >= V_FALL1:
            frames.append(fall1 if vy < V_FALL2 else fall2)
        elif abs(dt) <= lay.slash_window:
            # Wind up, strike, recover. Near the apex this becomes an air slash,
            # which is where the hops pay off visually.
            third = lay.slash_window * 2 / 3
            frames.append(combo[0] if dt < -lay.slash_window + third
                          else combo[1] if dt < -lay.slash_window + 2 * third
                          else combo[2])
        elif vy is not None:
            frames.append(rise)             # coasting through the apex band
        else:
            # Phase advances only while grounded, so the run cycle stays
            # continuous across hops instead of resuming on a random foot.
            frames.append(run[run_phase % 8])
            run_phase += 1

    a(f'<g transform="translate({lay.x_start},{lay.sprite_y})">'
      f'<animateTransform attributeName="transform" type="translate" '
      f'values="{";".join(pos)}" dur="{num(DUR)}s" calcMode="linear" '
      f'repeatCount="indefinite"/>'
      f'<g clip-path="url(#fclip)"><g>'
      f'<animateTransform attributeName="transform" type="translate" '
      f'values="{";".join(str(-i * fw) for i in frames)}" dur="{num(DUR)}s" '
      f'calcMode="discrete" repeatCount="indefinite"/>'
      f'<use xlink:href="#sheet"/></g></g></g>')

    a(f'<g font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12">'
      f'<text x="{MARGIN_X}" y="{lay.h - 7}" font-weight="700" '
      f'fill="{T["title"]}">SLAY RAT</text>'
      f'<text x="{MARGIN_X + 72}" y="{lay.h - 7}" fill="{T["text"]}">'
      f'vs. {total:,} contributions</text>'
      f'<text x="{lay.w - MARGIN_X - 124}" y="{lay.h - 7}" fill="{T["text"]}" '
      f'text-anchor="end">{len(cells)} days slain</text>'
      f'<text x="{lay.w - MARGIN_X}" y="{lay.h - 7}" font-weight="700" '
      f'fill="{T["gold"]}" text-anchor="end">slayrat.com &#8599;</text></g>')

    a('</svg>')
    return "".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("calendar", nargs="?", default=os.path.join(HERE, "contrib.json"),
                    help="contribution calendar JSON (default: ./contrib.json)")
    ap.add_argument("-o", "--out-dir", default=os.path.join(HERE, "out"))
    args = ap.parse_args(argv)

    sp = load_sprite()
    cal, cells = load_calendar(args.calendar)
    weeks = len(cal.get("weeks", []))
    if not weeks:
        sys.exit("calendar has no weeks")

    lay = Layout(weeks, sp["frameW"], sp["frameH"])
    os.makedirs(args.out_dir, exist_ok=True)
    for theme in THEMES:
        svg = build(theme, cal, cells, sp, lay)
        path = os.path.join(args.out_dir, f"slayrat-{theme}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"{path}  {len(svg) / 1024:.0f} KB  {weeks} weeks  "
              f"{len(cells)} cells  {len({c['w'] for c in cells})} weeks hit")


if __name__ == "__main__":
    main()
