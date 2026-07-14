"""3ds Max startup hook — copy this file into
  %LOCALAPPDATA%/Autodesk/3dsMax/<version> - 64bit/ENU/scripts/startup/
and set LIGHTMATCH_MAX_REPO below (or the LIGHTMATCH_MAX env var) to the repo path.
It registers a "LightMatch" macroscript under category "LightMatch" — bind it to a
toolbar button / hotkey via Customize → Customize User Interface."""

import os
import sys

# The repo path comes from the LIGHTMATCH_MAX env var. This file is COPIED out of the
# repo into Max's startup dir, so __file__ can't locate the clone — the env var is the
# only reliable source. Default to empty (NOT a hardcoded machine path): a stale default
# would silently insert a non-existent path and make `import lightmatch_max` fail with no
# visible reason (found in the launch-readiness audit).
LIGHTMATCH_MAX_REPO = os.environ.get("LIGHTMATCH_MAX", "")


def _prep_path():
    """Interactive 3ds Max's Python doesn't auto-initialize site.py, so the user-site
    directory (where bundled-pip fallback installs) is not on sys.path — add it now so
    the deps check inside bootstrap.launch() finds numpy/PIL/requests. Idempotent."""
    if not LIGHTMATCH_MAX_REPO:
        print("[lightmatch-max] Set the LIGHTMATCH_MAX env var to your clone path "
              r"(e.g. C:\Users\you\3dspluginlight) and restart Max.")
    elif not os.path.isdir(LIGHTMATCH_MAX_REPO):
        print(f"[lightmatch-max] LIGHTMATCH_MAX points to a missing folder: {LIGHTMATCH_MAX_REPO!r} — "
              r"set it to your clone (e.g. C:\Users\you\3dspluginlight) and restart Max.")
    elif LIGHTMATCH_MAX_REPO not in sys.path:
        sys.path.insert(0, LIGHTMATCH_MAX_REPO)
    try:
        import site
        usp = site.getusersitepackages()
    except Exception:
        usp = None
    if usp and usp not in sys.path and os.path.isdir(usp):
        sys.path.insert(0, usp)


def _register():
    _prep_path()
    from pymxs import runtime as rt  # type: ignore

    rt.macros.new(
        "LightMatch",
        "LightMatch",
        "Open LightMatch — match your render's lighting to a reference",
        "LightMatch",
        # Inline sys.path setup BEFORE importing bootstrap — interactive 3ds Max's
        # python.Execute doesn't auto-init site.py, so user-site-packages is missing
        # from sys.path. The bootstrap itself has belt-and-suspenders for this too;
        # this is just the most aggressive first line of defense (zero cache risk).
        'python.Execute "import sys, os; '
        '[sys.path.insert(0, p) for p in ['
        "os.path.join(os.environ.get('APPDATA', ''), 'Python', 'Python311', 'site-packages'), "
        "os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Python', 'Python311', 'site-packages')"
        '] if p and os.path.isdir(p)]; '
        'import lightmatch_max.bootstrap as _lmb; _lmb.launch()"',
    )


try:
    _register()
except Exception as e:  # never break Max startup
    print(f"[lightmatch-max] startup registration failed: {e} — is LIGHTMATCH_MAX set to your clone path?")
