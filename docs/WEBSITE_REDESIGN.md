# Website redesign log

Running log of the deliberate moves away from the "AI-generated" feel of the
first draft. The brand brief still holds (`PRODUCT.md`: precise instrument, calm
not alarm, self-audit, anti-slop); this doc records *what we're changing and why*,
plus the research to act on it.

## 1. Colour — dropping black + purple entirely

**Decision:** the near-black + violet palette is being replaced. Black-background
+ purple/violet accent is the single most common LLM-default aesthetic — it reads
"generic AI" no matter how clean the execution, which directly undercuts the whole
point (looking hand-made and trustworthy). The signature opener stays; the colour
system underneath it changes.

**Constraints for the new palette:**
- Pick one *confident, non-default* direction (avoid the dark-mode + neon cliché).
- Define in **OKLCH** (as the current tokens are), so swapping is a token edit in
  `web/src/styles/global.css`, not a rewrite.
- Hold **WCAG AA** contrast (body ≥ 4.5:1) — verify, don't eyeball.
- Stay legible for severity semantics (critical/high/low must still read without
  relying on hue alone).

**Directions worth testing (not decided — explore with the tools below):**
- Warm "editorial" light theme (off-white/paper + ink + one sharp accent) — the
  opposite of dark-SaaS, reads premium and human.
- High-contrast monochrome + a single *unexpected* accent (oxblood, acid lime,
  electric tangerine, deep teal) instead of violet.
- Duotone / restrained two-colour system.

**Colour tools:**
- [Coolors](https://coolors.co) — fast generator, lock + image-extract, contrast checker.
- [Realtime Colors](https://realtimecolors.com) — preview a palette on a real UI before committing (best for sanity-checking).
- [Khroma](https://khroma.co) — AI trained on 50 colours you pick (finds *your* taste, not the default).
- [Huemint](https://huemint.com) — AI brand/website palettes with colour-relationship control.
- [Adobe Color](https://color.adobe.com) — harmony rules (analogous/triadic/complementary) when you want precision.
- [Inclusive Colors](https://www.inclusivecolors.com) · [WebAIM Contrast](https://webaim.org/resources/contrastchecker/) · Stark — accessibility/contrast verification.

## 2. Hero — a high-end 3D / animated component

Replacing the static hero with one striking animated piece. Concepts on the table:
- **Rotating globe with a graph/arcs growing over it** — your data points lighting
  up and connecting across the world (exposure spreading / being mapped).
- **"Ares with a scope"** — a figure turns and looks straight at the viewer through
  a scope. Cinematic, ties to the name, unmistakably not a template.
- Or a more **abstract** interesting component (particles, fluid, instrument motif).

**Build approaches** (choose per concept; performance matters — the rest of the
site is zero-JS and must stay that way, so whatever we pick gets **isolated** as an
island or a video, lazy-loaded, with a static poster + `prefers-reduced-motion`
fallback):

| # | Approach | Best for | Trade-offs |
|---|---|---|---|
| **A** | **Pre-rendered video loop via Higgsfield** (image→video) | the cinematic "Ares turns + looks through scope" | Very performant (just a `<video>`, no WebGL), filmic, achievable with no 3D skills. But baked/non-interactive, larger file (optimize/serve `webm`+`mp4`), short loop (3–10s). |
| **B** | **Lightweight WebGL globe** — [cobe](https://github.com/shuding/cobe) (5KB) or [globe.gl / react-globe.gl](https://globe.gl) | the globe + growing graph (arcs/points) | Interactive, data-driven, on-concept. Moderate JS; isolate + lazy-load. |
| **C** | **Three.js / React Three Fiber + drei + GSAP ScrollTrigger** | a custom scroll-driven 3D model (Ares bust / scope) | Max control, heaviest, most effort; needs a 3D asset (Blender/Spline). |
| **D** | **No-code 3D — [Spline](https://spline.design)** | designer-built 3D, export/embed | Middle ground; easy to make, watch bundle weight on embed. |

**The Higgsfield pipeline (approach A), since the user already knows this flow):**
still key-art (the Ares-with-scope or globe hero frame) → Higgsfield
[image-to-video](https://higgsfield.ai/blog/Best-Image-to-Video-AI-Tools-on-Higgsfield)
/ Draw-to-Video (WAN / Sora motion) → enhance + upscale → export up to 4K →
ship as `muted autoplay loop playsinline <video>` with a poster image and a
reduced-motion fallback to the still. This keeps the hero cinematic *and* cheap to
load (no 3D runtime). Strong default for the "Ares" concept.

## 3. Reference sites to study

**Galleries / inspiration:**
- [Awwwards](https://www.awwwards.com) (filter by 3D / WebGL) · [Godly](https://godly.website) · [Codrops](https://tympanus.net/codrops/) (tutorials + demos for exactly these effects)
- [Lapa Ninja](https://www.lapa.ninja) · [Land-book](https://land-book.com) · [Refero](https://refero.design)
- [Best 3D websites 2026 (MDX)](https://mdx.so/blog/best-3d-websites-2026-examples)

**Copy-paste animated/3D component libraries:**
- [Aceternity UI](https://ui.aceternity.com) (lots of flashy animated/3D heroes) · [Magic UI](https://magicui.design) (has the cobe-based Globe) · [React Bits](https://reactbits.dev) · [21st.dev](https://21st.dev)

**WebGL / 3D engines & assets:**
- [Three.js examples](https://threejs.org/examples) · [React Three Fiber + drei](https://docs.pmnd.rs/react-three-fiber) · [Spline community](https://spline.design/community) · [cobe](https://github.com/shuding/cobe) · [globe.gl](https://globe.gl)

## Open / next

- Choose the new **palette** (via §1 tools) → I rebuild the OKLCH tokens in
  `global.css` and re-skin in one pass.
- Choose the **hero concept + approach** (A–D) → build it isolated, lazy, with a
  reduced-motion fallback.
</content>
