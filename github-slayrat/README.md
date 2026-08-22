# github-slayrat

Renders a GitHub contribution calendar as Sooz slashing her way across it. Every
week with commits gets an arc slash, every contribution throws a coin, and she
hops to reach the high rows. Drop-in replacement for
[github-breakout](https://github.com/cyprieng/github-breakout) on a profile README.

Output is a self-contained animated SVG (SMIL), ~386 KB per theme, of which
~205 KB is the base64 sprite strip. Nothing is fetched at view time.

Requires Python 3.9+. `gen.py` and `fetch_contrib.py` are pure standard library;
only `prep_sprites.py` needs Pillow, and only when the source art changes.

## Preview

```sh
python3 fetch_contrib.py <your-username>   # writes contrib.json
python3 gen.py                             # writes out/slayrat-{dark,light}.svg
python3 build_readme_preview.py            # writes the preview pages
open out/readme-preview.html
```

No server needed, it all runs off `file://`. The hub links to three pages:

| Page | What it shows |
| --- | --- |
| `readme-dark.html` | The whole profile README on GitHub dark, with Sooz in place of breakout |
| `readme-light.html` | The same on GitHub light |
| `preview.html` | Just the graphic, both themes, with replay buttons |

`build_readme_preview.py` pulls the live README from the profile repo, swaps the
`<picture>` block, and renders it through **GitHub's own `/markdown` API**. The
preview therefore passes the same sanitizer the real page uses, which makes it
proof rather than a mockup: if the graphic would be stripped, it is stripped
here too. `--check` exits non-zero when that happens, so it works in CI.

Each page opens standalone on purpose. Chrome throttles SMIL animation inside an
iframe, so a framed side-by-side view shows a frozen first frame and makes
working artwork look broken.

> If you ever verify this through browser automation rather than by eye: Chrome
> also pauses animated images in a backgrounded tab, and `getCurrentTime()`
> reports `0` on `<object>`-embedded SVGs regardless of the real clock. Both look
> exactly like broken artwork. Check a trivial known-good animated SVG first.

## Where the data comes from

`fetch_contrib.py` reads `https://github.com/users/<login>/contributions`, the
same public endpoint the profile page renders. **No authentication**, which is
why the CI job needs no secrets.

This is deliberate, not just convenient. The GraphQL `contributionsCollection`
returns only what the calling token can see; for this account it reported 1,075
against the 1,435 the profile shows visitors. A banner that contradicts the
profile header directly above it is worse than no banner. The output matches the
GraphQL response shape, so `gen.py` consumes either source.

## Sprites

`prep_sprites.py` crops 16 frames out of the Sooz sheets in
`../slayrat/assets/processed/` (override with `--assets` or `$SLAYRAT_ASSETS`),
packs them into one strip on a shared alpha bounding box so they stay
registered, and writes `sooz-strip.json`. Re-run it only when the art changes.
`sooz-strip.json` is committed so CI never needs the game repo.

**Do not quantise the palette.** The art is shaded, not flat pixel art: each
frame carries ~2000 colours. An earlier version squeezed the strip to 63
colours, which turned black `#000000` into magenta `#350033` and mapped the same
shading to different palette entries per frame, so she visibly shimmered as she
ran. `prep_sprites.py` now measures colour error for every candidate encoding
and refuses anything above `ERR_LIMIT`. Even 256 colours drifts by 2.2 while
saving only 9%, so it ships full RGBA.

## How the animation is wired

Everything rides one 9 second master clock with `repeatCount="indefinite"`, so
the loop is seamless and no element needs its own `begin` offset. 874 animation
elements, all on that one timeline.

- **Sooz** is a single `<image>` of the sprite strip inside a `clipPath` one
  frame wide. A `calcMode="linear"` translate walks her across; a second
  `calcMode="discrete"` translate steps the strip left one frame width at a
  time, which is the sprite animation.
- **Cells** scale to 0 when the blade reaches their column.
- **Coins** use `<animateMotion>` with `keyPoints="0;0;1;1"`, so each holds at
  its start, flies during its own window, then holds at the end. That is what
  lets hundreds of coins share one global timeline.

### Two things that will silently break if you touch them

**The position track needs `NF + 1` samples, the frame track `NF`.** With no
explicit `keyTimes`, SMIL spreads N values over N−1 intervals. Emitting `NF`
position samples runs the walk 1/NF fast, desyncs it from the discrete frame
track, and leaves a visible snap at the loop point because the last sample never
reaches `x_end`.

**A bare `<animate>` targets its parent element.** The coin spin lives inside
each `<ellipse>`, not in the wrapping `<g>`. Put it in the `<g>` and it animates
a nonexistent `rx` on the group: no error, no spin, static discs.

Every `keyTimes` list goes through `keytimes()`, which clamps to [0,1] and
forces non-decreasing order. SMIL drops an animation outright if keyTimes are
out of order or out of range, and it fails silently in a 386 KB file.

## The jump is the game's jump

Do not replace this with a parabola. The first version used a symmetric arc and
read as moon gravity next to real gameplay. The feel comes from **asymmetric
gravity**, straight out of `src/game/entities.js`:

| From the game | Value | Effect |
| --- | --- | --- |
| `GRAV_UP` | `0.42` | slow float upward |
| `GRAV_DOWN` | `0.68` | fast drop |
| `JUMP` | `-6.6` | takeoff velocity |

`_jump_curve()` integrates exactly that at the game's own 1/60 tick, giving a
0.467s hop: 0.250s up, 0.217s down. Height is scaled to whatever the target cell
needs; the *shape* stays the game's. Air frames are picked by the same `vy`
thresholds the game uses:

```js
p.vy < -1.6 ? rise : p.vy < 1.2 ? apex : p.vy < 4.2 ? fall1 : fall2
```

`apex` is not packed into the strip: every hop's apex coincides with a hit, so
the slash combo always wins there and the frame would be dead weight.

Hops may not overlap. Hits land every ~0.18s against 0.467s of airtime, so
without that guard she merges into a permanent hover and never touches the
ground. `GROUND_MIN` forces visible running between hops.

## Tuning knobs

All in `gen.py`:

| Knob | Now | What it does |
| --- | --- | --- |
| `DUR` | `9.0` | Loop length. Lower is faster. Other timings scale off it via `_S`. |
| `STRIDE` | `41.0` | Px per 8-frame run cycle. `fps` derives from this and her speed so her feet stay planted. |
| `MIN_LIFT` / `MAX_LIFT` | `30` / `76` | Which weeks earn a hop, and how high. |
| `GROUND_MIN` | `0.22` | Forced seconds grounded between hops. |
| `CELL` / `PITCH` | `14` / `18` | Cell size, which sets the whole banner scale. |
| `SWORD` | `96` | X offset inside her frame where the blade lands. Keeps the slash synced to the cells popping. |

Do not set `fps` or `slash_window` by hand. `fps` falls out of `8 * speed /
STRIDE` so speed and stride cannot drift apart, and `slash_window` is `1.5 / fps`
so a hit is exactly the three combo frames. At ~49 target weeks a wider window
swallows the run and air frames whole.

Current mix: 20% running, 35% slashing, 37% airborne, 9% outro.

## Profile README changes

`patch_readme.py` applies two edits to the local `profile-README.md`. It is
idempotent, and it does not touch the remote.

1. **Links the graph to slayrat.com.** An `<a>` *inside* the SVG would be inert:
   links in an SVG do not work when it is served through `<img>`, which is how
   GitHub serves it. The anchor has to wrap the `<picture>` in the markdown. The
   `slayrat.com` wordmark in the caption is what signals it is clickable.
2. **Unstacks the footer badges.** They sat as bare lines inside
   `<div align="center">`, and GFM turns each newline there into a `<br>`, so
   every badge got its own row. Wrapping them in an explicit `<p>` makes markdown
   pass the block through as raw HTML untouched, which is why the badges at the
   top of the README were always fine.

## Deploying

The job lives at [`.github/workflows/slayrat.yml`](../.github/workflows/slayrat.yml)
in this repo. It mirrors the existing breakout job: fetch, render, force-push both SVGs to an
orphan `slayrat` branch. No secrets, no `pip install`. Then point the README at
that branch inside a `<picture>` that swaps on `prefers-color-scheme`.

## Caveats

- The graph is served straight from `raw.githubusercontent.com`, not through
  GitHub's Camo proxy: Camo only fronts third-party hosts, and raw is
  first-party. Verified on the live profile. That means no Camo cache lag, and
  `cache-control: max-age=300`, so a regenerated SVG appears within 5 minutes.
  The shields.io badges elsewhere in the README *are* Camo-proxied; do not
  confuse the two.
- SMIL cannot honour `prefers-reduced-motion` when served through an `<img>`,
  the same tradeoff breakout already makes.
- 386 KB is a large README image. Most of it is the sprite strip, and it is
  Camo-cached after first load, but it is not nothing.
- `fetch_contrib.py` parses HTML. It fails loudly if GitHub's markup changes
  rather than emitting a silently empty calendar.

## Licence

Code is MIT. The Slay Rat character art is not: see [LICENSE](LICENSE).
