# Light for 3ds Max

*(formerly LightMatch — the dock is titled **Light**)*

Match your render's lighting to any reference — **natively inside 3ds Max**. Drop a
reference image, grab your current render straight from the V-Ray frame buffer, and
Light measures both frames, returns an exact V-Ray recipe, **applies it as one
undoable step**, then re-renders and re-measures until the lighting is within noise
of the reference (97%+ measured match).

This is the native sibling of the [LightMatch web app](https://github.com/Aasishmuchala/LIGHTROOM).
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
- **Camera-scoped, bring-your-own-render** — pick the camera you're solving from a live
  list of the scene's cameras (passive — it just scopes which camera your exposure moves
  target); `cam.iso/fnumber/shutter` are stamped with THAT camera's exact node, so they
  land on it, never on the renderer's first-of-kind. And you don't have to auto-render:
  **Base…** loads your own render file as the base (manual path — works even outside
  Max), so the loop runs on the exact frame you rendered.
- **Per-camera workflow** — a session carries many cameras, and each camera keeps its
  OWN reference, your loaded render, recipe, refine history, and a saved LIGHTING look.
  Pick a camera in the dock and its whole state RECALLS — a pure panel swap, no scene
  change. **Save look** snapshots that camera's lighting (sun/lights/color-mapping/gamma/
  exposure) and **Restore look** re-applies it in one undo step (read-back verified,
  cam-exposure targeted at the picked camera). Opt-in **Auto lighting on switch** (OFF by
  default) does save-on-leave / restore-on-enter as you switch — the one control that
  mutates the scene on a switch, and every auto switch is disclosed in the status bar.
- **Cinematic depth** — a Z-depth pass feeds measured depth structure: subject-vs-
  background separation in stops, aerial-perspective (lifted far blacks + compressed far
  contrast), per-band tonal profile — the model speaks DP, not histogram.
- **Autopilot with keep-best** — one button runs the whole loop unattended: render →
  check → apply → repeat until measured-matched (with oscillation/budget guards), each
  round one undo step. Every round's state is snapshotted; on any exit that isn't
  "matched" the scene is rolled back to the **best-scoring** round, never left at a bad
  last guess.
- **Chaos Vantage live-link, first-class** — the Vantage live-link is a running V-Ray
  GPU IPR, and Light's sun/light moves are exactly the scene-node changes it streams.
  The dock **detects** whether the link is running ("✓ streaming" / "○ start it"),
  **starts or refreshes it in one click** (⚡ Vantage link — using Chaos' own reversible
  entry point, which backs up and restores your DR state), nudges it after Apply/Restore
  so lighting changes reliably propagate, and labels the moves Vantage can't see
  (camera exposure / color mapping render in the V-Ray VFB only — Vantage has its own
  camera) as **"V-Ray-render only."**
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
- Python deps into Max's user-site once (Max's bundled Python has no pip, and V-Ray's
  native module needs numpy 1.x — so pin `numpy<2`):
  `python -m pip install --python-version 3.11 --only-binary=:all: --target "%APPDATA%\Python\Python311\site-packages" "numpy<2" Pillow requests`

## Install

1. Clone this repo anywhere on the machine that runs Max. Note its absolute path.
2. Copy `startup/lightmatch_max_startup.py` into
   `%LOCALAPPDATA%/Autodesk/3dsMax/<ver> - 64bit/ENU/scripts/startup/`.
3. **Point the plugin at THIS clone.** The startup script reads the repo path from the
   `LIGHTMATCH_MAX` env var — there is no default. Set it to the absolute path of the repo
   you cloned in step 1 (or edit `LIGHTMATCH_MAX_REPO` at the top of the copied startup
   script). If it's unset or wrong, the MAXScript listener prints a clear hint and the
   dock simply won't register — never a silent failure.
4. Restart Max → Customize → Customize User Interface → category **LightMatch** →
   drag the action onto a toolbar.

## The loop

1. **Reference…** — pick the look you want.
2. **Camera** — pick the camera you're solving from the dock list. Each camera is its own
   mini-session: its reference, your render, recipe, and refine history RECALL when you
   pick it (a pure panel swap, no scene change). It's *passive*: it scopes which camera
   your exposure moves target, and doesn't touch the viewport unless you ask. Exposure
   moves (`cam.iso/fnumber/shutter`) are stamped with the picked camera's exact node, so
   they land on THAT camera, not the renderer's first-of-kind. Optional: **Render camera**
   points the viewport at the picked camera and renders IT.
3. **Base…** or **Grab VFB** — provide your render. **Base…** loads your own render file
   (manual path, no auto-render — works even outside Max); **Grab VFB** / **Render view**
   / **Render camera** are optional auto-render conveniences that read the frame buffer
   directly, no export.
4. Set scene / time-of-day / rig; tick **Lock scene globals** for per-area passes on
   a big project (sun/sky/fog/color-mapping stay frozen; the recipe solves with
   camera + local lights only, and any global move the model tries is withheld and
   disclosed).
5. **Analyze the match** — exact controls with `from → to` and why.
6. Untick anything you don't want, **Apply** (one undo step), **Re-render & Check** —
   a measured % match and a 3–5-move trim card each round, until **MATCHED**.
7. *(Optional)* **Save look** snapshots this camera's whole lighting (sun/lights/color-
   mapping/gamma/exposure); **Restore look** re-applies it in one undo step. Tick **Auto
   lighting on switch** (OFF by default) to save-on-leave / restore-on-enter automatically
   — the only thing that changes your scene when you switch cameras, and each switch is
   disclosed in the status bar.
8. *(Optional, Chaos Vantage)* Click **⚡ Vantage link** to start the live-link (V-Ray
   GPU only) or refresh it if it's already running — every sun/light move then streams
   into Vantage in real time. The apply status tells you whether the link is active, and
   flags any move that only affects the V-Ray frame buffer ("won't show in Chaos
   Vantage"). Autopilot refreshes the link once on completion so Vantage ends on the
   matched look.

## Development

```
python -m pip install -e .[dev,ui]
pytest                                 # 115 core tests (TS↔numpy parity, engine, stress, census, autopilot, camera scope, per-camera session + looks, Vantage live-link)
pytest -m ui -k <one_test_name>        # offscreen dock-flow suite — run ONE test per process (see below)
python scripts/smoke_headless.py       # SMOKE_OK — core, anywhere
```

Every UI id passes; run the offscreen suite **one test per process** (`-k` a single
name, or a wrapper that spawns each). Each test passes on its own — PySide6 6.11 only
aborts the interpreter on *multi-test* Qt teardown in the pytest harness (the exit code,
not the flake, is authoritative), so the suite is excluded from the default `pytest` run.

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
1. The dock opens as a floating tool panel (parented above the Max main window).
2. A real reference + VFB grab → Analyze returns a recipe (try **Consensus ×3** for a
   steadier first pass, at 3× cost).
3. Checked Apply changes the scene and a **single Ctrl+Z** reverts the whole recipe;
   any value that didn't take shows as "⚠ NOT VERIFIED".
4. Re-render & Check scores and shows a correction; ▶ Autopilot runs the loop unattended.
5. **Float VFB calibration (optional):** float/EXR scene-referred capture is BUILT but
   OFF by default — it self-gates to the safe 8-bit path unless it detects true HDR
   pixels. Confirming the VFB channel is linear on your build is a one-time live check
   before trusting exact (vs. display-approximate) exposure/CCT.
6. **Cinematic depth (optional):** tick **Cinematic depth** to render a V-Ray Z pass
   alongside Analyze/Check and feed the model measured subject/background separation and
   aerial haze. OFF by default (one extra render); a Z pass that isn't clean is skipped
   automatically, so it never feeds guessed numbers.
7. **Sessions:** **Sessions ▾** reopens any past session or starts a new one — and a
   session now carries MANY cameras, each with its own reference, render, recipe, and
   saved lighting look. The menu shows a 📷 count; picking a camera recalls that camera's
   state. Pick up an area you were matching yesterday without re-importing.

Everything up to the live model round — including the main-thread marshalling and
autopilot — is machine-proven headlessly.

Re-sync the brain after web-repo changes:

```
cd ../lightmatch/web && npx tsx scripts/export-plugin-data.ts ../../lightmatch-max/data
```

## Status (v0.7)

The Vantage + polish arc. **Chaos Vantage live-link is first-class:** the plugin
understands that the live-link is a running V-Ray GPU IPR (read from Chaos' own
`Vantage-LiveLink.ms`), detects it (`livelink_active`), starts/refreshes it in one
click (**⚡ Vantage link** — via Chaos' reversible entry point so Distributed
Rendering is backed up/restored, GPU-gated so V-Ray CPU never trips Chaos' renderer-
switch modal), nudges it after Apply/Restore, and refreshes once when Autopilot
finishes so Vantage ends on the matched look. Every apply now discloses whether
scene changes are streaming, and `vfb`-domain moves (camera exposure / color
mapping) are labeled "won't show in Chaos Vantage." The writable vocabulary is
**44 verified parameters** (sun placement elevation/azimuth as one coupled sky-
sphere transform, light/dome Kelvin + RGB with color-mode handling, ambient light,
colors from names/hex/RGB/0–1 floats) — all prop names verified against live V-Ray
classes.

**Adversarially stress-tested, twice.** A 43-agent audit of the core (every
subsystem + every claim, findings independently refuted) confirmed 9 bugs — all
fixed: a leading thinking-spill JSON could shadow a valid recipe (`parse_json_from_text`
now prefers the object carrying `values`/`moves`), malformed gateway bodies crashed
past the retry loop, 0–1 float colours truncated to black, cm.type couldn't restore
deprecated gamma modes, Autopilot skipped the reference guard, and the "non-
destructive" diagnostic silently enabled camera Exposure. A second 16-agent audit of
the UI confirmed 12 more — all fixed — including two systemic ones: Qt's `*` QSS
font-size silently overrides every `QFont.setPointSize` (typography now lives in
objectName-scoped QSS rules), and `session["context"]` was never persisted (context
restore was a no-op since the feature shipped).

**Renamed "Light"** with a quiet-luxury dock: matte near-black, one champagne-gold
accent, wordmark header, letter-spaced section captions, capitalized context pickers
(display label + lowercase canonical itemData, so prompts and old sessions are
untouched), themed Sessions menu, and every button verified wired (22/22 signal
connections). Gates: **115 core tests**, in-Max `MAX_STRESS_OK` (full apply sweep,
hostile rejection, autopilot matched at 99% over real renders), gpt-5.5 gateway
verified live.

## Status (v0.6)

Camera arc complete (Stages 2–3 on top of Stage 1). **Stage 2 — per-camera session
model:** a session now holds many cameras (`cameras{name→slot}`), and each camera keeps
its OWN reference, base render, recipe, and refine history; picking a camera in the dock
RECALLS that camera's state as a pure panel swap — no scene change — and your loaded
render persists per camera. Legacy single-slot sessions MIGRATE on load, and the session
menu shows a 📷 camera count. **Stage 3 — per-camera lighting snapshots:** **Save look**
snapshots the scene's lighting (sun/lights/color-mapping/gamma/exposure) as a camera's
look and **Restore look** re-applies it in one undo step (read-back verified, cam-exposure
targeted at the picked camera); an opt-in **Auto lighting on switch** (OFF by default) does
save-on-leave / restore-on-enter as you switch cameras — the ONLY control that mutates the
scene on a switch, honoring "not automatic," and every auto switch is disclosed in the
status bar. Headless matrix green (**98 core** + tests/test_stress.py + the 11-id offscreen
UI suite; `smoke_headless.py` SMOKE_OK), and the **in-Max gate now also exercises the
Stage 3 save/restore round-trip** — **pending the user's live Max run** to sign it off.

## Status (v0.5)

Camera-scoped Stage 1. A live **camera picker** (populated from the scene) scopes which
camera your exposure moves target — *passive*, no viewport switch unless you ask — and a
**node-stamp** guarantees `cam.iso/fnumber/shutter` land on the PICKED camera's exact
node, never the renderer's first-of-kind. **Bring-your-own-render**: **Base…** loads your
own render file as the base (manual path — works even outside Max), so the loop runs on
the exact frame you rendered; `Render view` / `Render camera` stay optional auto-render
conveniences. The new `maxio` camera calls (`list_cameras` / `set_active_camera` /
`render_camera`) and `stamp_camera_node` are stress-hardened: the stamp is a total guard —
it returns a fresh list, NEVER mutates the caller's rows and NEVER raises, even on hostile
input (a non-str/unhashable `param`, an already-node-targeted row, or a non-dict just
passes through untouched). Headless matrix green (98 core + the offscreen UI suite;
`smoke_headless.py` SMOKE_OK), and the **in-Max gate now exercises the camera code** —
`scripts/smoke_max.py` certifies `list_cameras` / `set_active_camera` / `render_camera`
against real pymxs — **pending the user's live Max run** to sign it off.

## Status (v0.4)

Second review pass on top of v0.3. Wires the two **dormant** features live: **Cinematic
depth** (opt-in Z-pass evidence — subject separation + aerial haze — that degrades to
absent, never to wrong numbers) and a **Sessions** picker (reopen a past session's
reference + recipe, or start fresh). Hardens the plumbing: a timed-out main-thread call
is now cancelled so a "failed" apply can't mutate the scene later; the depth pipeline is
NaN-safe end-to-end (a single non-finite pixel no longer bypasses the beauty-identity
gate or crashes band stats); the float grab is size-capped so a full-res frame can't
stall the per-pixel read; and greyed-out buttons now say *why*. 91 pytest green (85 core
deterministic + 6 offscreen dock-flow; the UI suite carries a documented PySide 6.11
teardown flake and is excluded from the default run).

## Status (v0.3)

Adds pre-test hardening on top of v0.2: an in-Max **diagnostics** self-test, a
main-thread-marshaller **timeout** guard (no frozen Max), a depth-pass **sanity gate**
(a bad Z read can't mislead the model), **Consensus ×3** (median-merge three analyses
for a steadier first recipe), and a **float/EXR capture scaffold** (self-gating, OFF
until a live calibration confirms the VFB channel is linear). `MAX_STRESS_OK` validated
(consensus merged to the correct medians, diagnostics passed over real pymxs, float grab
safely fell back).

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
