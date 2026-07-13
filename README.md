# LightMatch for 3ds Max

Match your render's lighting to any reference — **natively inside 3ds Max**. Drop a
reference image, grab your current render straight from the V-Ray frame buffer, and
LightMatch measures both frames, returns an exact V-Ray recipe, **applies it as one
undoable step**, then re-renders and re-measures until the lighting is within noise
of the reference (97%+ measured match).

This is the native sibling of the [LightMatch web app](https://github.com/Aasishmuchala/LIGHTROOM)
(which remains the tool for **Chaos Vantage** — Vantage has no plugin surface).
The two share one brain: `data/*.json` (prompts, control packs, verified property
maps, and pixel-parity vectors) is **generated from the web repo's TypeScript
source** — nothing is hand-copied, so the two products can never drift.

## Why native beats the bridge

- **It understands the project** — a live SCENE CENSUS inventories every camera, light
  and sun BY NAME, the HDRI, gamma, and color mapping, and runs PRE-FLIGHT WARNINGS for
  the silent value-wreckers (environment/camera exposure control eating your EV moves,
  gamma ≠ 2.2, multiple suns, no camera). Most "the tool gave wrong values" cases are
  right values dropped into a scene state that ignores them — the census catches that
  before you render.
- **No wrong values** — every applied value is READ BACK and confirmed it actually
  landed; a silent no-op becomes a visible "⚠ NOT VERIFIED" instead of a quiet lie.
- **Per-fixture, per-area** — a move can name an exact light (`"node":
  "VRayLight_Kitchen_Fill"`), so on a big project you lock the globals (matched on a
  hero shot) and solve each room with its own camera + local fixtures.
- **Cinematic depth** — a Z-depth pass feeds measured depth structure: subject-vs-
  background separation in stops, aerial-perspective (lifted far blacks + compressed far
  contrast), per-band tonal profile — the model speaks DP, not histogram.
- **Autopilot** — one button runs the whole loop unattended: render → check → apply →
  repeat until measured-matched (with oscillation/budget guards), each round one undo
  step.
- **No exporting** — `Grab VFB` / `Render view` reads the frame buffer directly.
- **No assumed defaults** — the scene's real values are pulled live as the recipe's
  `from` baseline, every time.
- **Real apply** — recipe rows are set through pymxs (no MAXScript strings at all)
  inside one undo record: `Ctrl+Z` reverts the whole recipe.
- **Calibration probe** — measure the scene's real response to one knob, then scale
  every magnitude by that instead of the model's guess.
- **No server, no CORS, no localhost bridge** — the only network call is the AI
  round to your own omega gateway.

## Requirements

- 3ds Max **2025–2027** (PySide6 + Python 3.11+; validated pattern from Max 2026)
- V-Ray (CPU or GPU — renderer properties are discovered, never hard-coded)
- An omega gateway key (`oc_…`) — pasted once in the dock, stored in
  `%LOCALAPPDATA%/LightMatchMax/config.json`
- Python deps inside Max once: `"<max>/Python/python.exe" -m pip install numpy Pillow requests`

## Install

1. Clone this repo (say to `C:\Users\you\lightmatch-max`).
2. Copy `startup/lightmatch_max_startup.py` into
   `%LOCALAPPDATA%/Autodesk/3dsMax/<ver> - 64bit/ENU/scripts/startup/` and, if your
   clone lives elsewhere, set the `LIGHTMATCH_MAX` env var to the repo path.
3. Restart Max → Customize → Customize User Interface → category **LightMatch** →
   drag the action onto a toolbar.

## The loop

1. **Reference…** — pick the look you want.
2. **Grab VFB** (or **Render view**) — your render, no export.
3. Set scene / time-of-day / rig; tick **Lock scene globals** for per-area passes on
   a big project (sun/sky/fog/color-mapping stay frozen; the recipe solves with
   camera + local lights only, and any global move the model tries is withheld and
   disclosed).
4. **Analyze the match** — exact controls with `from → to` and why.
5. Untick anything you don't want, **Apply** (one undo step), **Re-render & Check** —
   a measured % match and a 3–5-move trim card each round, until **MATCHED**.

## Development

```
python -m pip install -e .[dev,ui]
pytest                                 # 44 tests: TS↔numpy parity, core, stress, offscreen dock flow
python scripts/smoke_headless.py       # SMOKE_OK — core, anywhere
```

In-Max validation (headless, real V-Ray scene):

```
powershell -Command "$env:LIGHTMATCH_MAX=$PWD; Start-Process '<max>/3dsmaxbatch.exe' '\"scripts/run_smoke.ms\"' -Wait -NoNewWindow"
# verdict → scripts/_smoke_result.txt  (MAX_SMOKE_OK)
# scripts/run_stress.ms → scripts/_stress_result.txt  (MAX_STRESS_OK): populated-scene
# pull, full apply sweep, hostile-apply rejection, and the end-to-end loop with two
# real renders + a real scene apply (the model is stubbed, so no key is needed).
```

3dsmaxbatch swallows Python stdout and coalesces undo into one hold, so the smokes
write a **result file** and treat per-record undo granularity as an interactive-only
check. Max's bundled Python has no pip — install cp311 wheels into its user site once:
`python -m pip install --python-version 3.11 --only-binary=:all: --target "%APPDATA%\Python\Python311\site-packages" "numpy<2" Pillow requests` (V-Ray's native module needs numpy 1.x).

### Interactive checklist (the one gate left before production use)

Run once inside a real Max session with a live key:
0. **Run diagnostics first** — the button self-tests the whole Max + gateway plumbing
   in ~10s (deps, renderer, pull, census + warnings, apply→read-back verify, the
   main-thread marshaller, and a gateway key ping). All ✓ means the real run will work.
1. The dock opens and docks.
2. A real reference + VFB grab → Analyze returns a recipe (try **Consensus ×3** for a
   steadier first pass, at 3× cost).
3. Checked Apply changes the scene and a **single Ctrl+Z** reverts the whole recipe;
   any value that didn't take shows as "⚠ NOT VERIFIED".
4. Re-render & Check scores and shows a correction; ▶ Autopilot runs the loop unattended.
5. **Float VFB calibration (optional):** float/EXR scene-referred capture is BUILT but
   OFF by default — it self-gates to the safe 8-bit path unless it detects true HDR
   pixels. Confirming the VFB channel is linear on your build is a one-time live check
   before trusting exact (vs. display-approximate) exposure/CCT.

Everything up to the live model round — including the main-thread marshalling and
autopilot — is machine-proven headlessly.

Re-sync the brain after web-repo changes:

```
cd ../lightmatch/web && npx tsx scripts/export-plugin-data.ts ../../lightmatch-max/data
```

## Status (v0.3)

Adds pre-test hardening on top of v0.2: an in-Max **diagnostics** self-test, a
main-thread-marshaller **timeout** guard (no frozen Max), a depth-pass **sanity gate**
(a bad Z read can't mislead the model), **Consensus ×3** (median-merge three analyses
for a steadier first recipe), and a **float/EXR capture scaffold** (self-gating, OFF
until a live calibration confirms the VFB channel is linear). 89 pytest green,
`MAX_STRESS_OK` re-validated (consensus merged to the correct medians, diagnostics
passed over real pymxs, float grab safely fell back).

## Status (v0.2)

Core (measurement, evidence, prompts, validation, Area mode, **scene census +
warnings, calibration probe, cinematic depth evidence, autopilot, named-node apply +
read-back verification**, omega client, session persistence) is complete and
**parity-tested** against the web implementation, plus an adversarial stress suite
(degenerate images, hostile model replies, corrupt sessions) and an **offscreen drive
of the real dock widget** (full click-path + autopilot with Max I/O and the gateway
stubbed). Validated headlessly on **real 3ds Max 2026.2 + V-Ray 7u3**: `MAX_SMOKE_OK`
and `MAX_STRESS_OK` — full end-to-end loop, census (caught a real GAMMA_OFF warning),
named-node apply verified on a specific fixture, and autopilot converged in 3 rounds
over real renders. **77 pytest green.** Next: the "operator line" chat and HDRI-finder
ports, and float/EXR VFB capture (v0.2 tonemaps to 8-bit; Z-depth is best-effort). The
interactive checklist above is the last gate before first production use.
