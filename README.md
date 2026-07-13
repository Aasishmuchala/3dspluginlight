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

- **No exporting** — `Grab VFB` / `Render view` reads the frame buffer directly.
- **No assumed defaults** — the scene's real values are pulled live as the recipe's
  `from` baseline, every time.
- **Real apply** — recipe rows are set through pymxs (no MAXScript strings at all)
  inside one undo record: `Ctrl+Z` reverts the whole recipe.
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

Run once inside a real Max session with a live key: (1) the dock opens and docks;
(2) a real reference + VFB grab → Analyze returns a recipe; (3) checked Apply changes
the scene and a **single Ctrl+Z** reverts the whole recipe; (4) Re-render & Check
scores and shows a correction. Everything up to the live model round is machine-proven.

Re-sync the brain after web-repo changes:

```
cd ../lightmatch/web && npx tsx scripts/export-plugin-data.ts ../../lightmatch-max/data
```

## Status (v0.1)

Core (measurement, evidence, prompts, validation, Area mode, omega client, session
persistence) is complete and **parity-tested** against the web implementation, plus an
adversarial stress suite (degenerate images, hostile model replies, corrupt sessions)
and an **offscreen drive of the real dock widget** (the full click-path with Max I/O
and the gateway stubbed). Validated headlessly on **real 3ds Max 2026.2 + V-Ray 7u3**:
`MAX_SMOKE_OK` and `MAX_STRESS_OK` (full end-to-end loop, two real renders, one real
scene apply). 44 pytest green. Next ports: the "operator line" chat and the HDRI
finder. The interactive checklist above is the last gate before first production use.
