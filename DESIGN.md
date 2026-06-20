# Design

Visual system for the Aresis brand site. Seeded pre-implementation; re-run
`/impeccable document` once the site has real tokens to capture the built system.

## Theme

Dark-first, near-black, high-craft, restrained. The mood: *a precision
instrument in a dark room — matte black surfaces, a single violet light source.*
Premium, technical, calm. Generous negative space; the violet is rare and
deliberate, never decorative wallpaper. Reference feel (not literal copy):
Raycast — depth from subtle elevation and hairlines, not heavy borders or
shadows; speed and quiet confidence over ornamentation.

## Color

OKLCH throughout. Near-black base, near-white ink, one violet accent used
sparingly. (Brand seed override: `palette.mjs` suggested an amber seed, but the
user-committed direction is dark violet — identity direction wins.)

| Token | OKLCH | Role |
|---|---|---|
| `--bg` | `oklch(0.145 0.006 295)` | page background — near-black, faint cool-violet tint |
| `--surface` | `oklch(0.185 0.008 295)` | raised panels / cards |
| `--surface-2` | `oklch(0.225 0.010 295)` | hover / nested surface |
| `--ink` | `oklch(0.965 0.004 295)` | primary text (≈ white) |
| `--muted` | `oklch(0.74 0.012 295)` | secondary text — verified ≥ 4.5:1 on `--bg` |
| `--faint` | `oklch(0.60 0.012 295)` | tertiary / captions (large or non-essential only) |
| `--accent` | `oklch(0.62 0.20 293)` | dark violet — primary actions, key emphasis |
| `--accent-bright` | `oklch(0.72 0.17 293)` | violet text-on-dark, hover, focus ring |
| `--accent-dim` | `oklch(0.40 0.12 293)` | low-emphasis violet (subtle glows, borders) |
| `--hairline` | `oklch(1 0 0 / 0.09)` | 1px separators / borders |
| `--hairline-strong` | `oklch(1 0 0 / 0.16)` | emphasized borders, focus |

Severity scale (calm, not alarm — used as small labels, never full-bleed red):
`critical` violet-leaning red `oklch(0.62 0.20 18)`, `high` amber
`oklch(0.74 0.15 70)`, `medium` `oklch(0.80 0.11 95)`, `low/info` `--faint`.
Always paired with a text label + icon, never color alone.

Accent discipline: violet appears on ~1 primary CTA per view, active states,
focus rings, and at most one ambient glow per section. If everything is violet,
nothing is.

## Typography

Self-hosted (no Google CDN — see Principle 1). Pair on a contrast axis
(proportional sans + monospace), not two similar sans.

- **Display + body:** **Geist Sans** (variable). Clean technical grotesque;
  modern, precise, not Inter. Headings tight but not cramped.
- **Technical accents:** **Geist Mono** — eyebrows/kickers, step numbers, data,
  severity labels, finding locators. The mono is what makes it read "instrument."

Scale (fluid `clamp()`): hero display max ≤ 6rem (~96px) ceiling; don't shout.
Display letter-spacing ≥ -0.03em (tight, letters never touch). Body 16–18px,
line-height ~1.6, line length capped 65–75ch. `text-wrap: balance` on h1–h3,
`text-wrap: pretty` on prose. Mono eyebrows: ~12–13px, letter-spacing +0.08em,
uppercase.

## Layout

- Max content width ~1120px; comfortable gutters; lots of vertical air between
  sections (generous, not enterprise-dense).
- 8px spacing base; sections separated by space + hairlines, not boxes.
- Depth from subtle elevation (`--surface` lift + a hairline + a faint violet
  inner glow on key cards), never heavy drop shadows.
- Responsive: single-column mobile-first; grids collapse cleanly; nav → minimal.

## Components

- **Buttons:** primary = solid `--accent`, ink-on-accent text, subtle violet
  glow on hover; secondary = transparent with `--hairline` border. Crisp, ~10px
  radius, fast transitions.
- **Cards:** `--surface`, 1px `--hairline`, ~14px radius; on hover lift to
  `--surface-2` + `--hairline-strong`. Restrained.
- **Eyebrow/kicker:** Geist Mono, uppercase, `--accent-bright` or `--muted`.
- **Severity chip:** mono label + dot, severity color, low-key.
- **Inputs (waitlist):** dark field, `--hairline` border → `--accent` focus ring.

## Motion

GPU-only: animate `transform` and `opacity` exclusively (never width/height/top/
left). Restrained and fast — micro, not theatrical.

- Scroll-reveal: subtle fade + 8–12px rise as sections enter (IntersectionObserver
  or `animation-timeline: view()` with fallback). Stagger lightly.
- Hover: 120–180ms ease transitions on buttons/cards; faint violet glow.
- One tasteful ambient hero element (slow, low-opacity violet gradient/grid),
  GPU-composited, paused under reduced motion.
- **`prefers-reduced-motion: reduce` disables all of it** — content is fully
  understandable static. Motion is never required.

## Anti-slop guardrails (from PRODUCT.md anti-references)

No blurple gradient hero, no Inter, no identical rounded feature-card rows, no
red FUD walls, no terminal-green, no badge soup, no third-party font/analytics
CDN. Commit to the black + single-violet direction with real hierarchy.
</content>
