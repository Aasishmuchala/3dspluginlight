"""Frame capture — the plugin's killer UX over the web app: no exporting from the
VFB, no drag-drop. Grab the LAST V-Ray render straight from the frame buffer (or
kick a fresh render) and measure it in place."""

from __future__ import annotations

import os
import tempfile

from .scene import LightMatchMaxError, _rt


def _bitmap_to_pil(rt, bmp):
    from PIL import Image

    path = os.path.join(tempfile.gettempdir(), "lightmatch_grab.png")
    try:
        bmp.filename = path
        rt.save(bmp)
    finally:
        try:
            rt.close(bmp)
        except Exception:
            pass
    img = Image.open(path)
    img.load()
    return img


def grab_vfb():
    """The CURRENT V-Ray frame buffer contents (channel 0 = RGB color), as a PIL
    image. Falls back with a clean error when no VFB image exists yet."""
    rt = _rt()
    fn = getattr(rt, "vrayVFBGetChannelBitmap", None)
    if fn is None:
        raise LightMatchMaxError("V-Ray VFB functions unavailable — is V-Ray the active renderer?")
    try:
        bmp = fn(0)
    except Exception as e:
        raise LightMatchMaxError(f"Could not read the VFB: {e}") from e
    if bmp is None:
        raise LightMatchMaxError("The VFB is empty — render once, then grab.")
    return _bitmap_to_pil(rt, bmp)


def render_view(width: int = 0, height: int = 0):
    """Kick a render of the active view and return it as a PIL image (blocking).
    Zero width/height = the scene's current output size."""
    rt = _rt()
    try:
        if width and height:
            bmp = rt.render(outputSize=rt.Point2(width, height), vfb=False)
        else:
            bmp = rt.render(vfb=False)
    except Exception as e:
        raise LightMatchMaxError(f"Render failed: {e}") from e
    return _bitmap_to_pil(rt, bmp)


def grab_z_depth(width: int = 0, height: int = 0):
    """Best-effort Z-depth pass for the cinematic-depth evidence: ensure a VRayZDepth
    render element exists (auto-ranged), render, and return its channel as a float
    numpy array (H×W, larger = farther) — or None if a Z pass can't be produced. Depth
    evidence is a bonus signal, so this NEVER raises; it degrades to None and the round
    just skips depth.
    """
    try:
        import numpy as np
        rt = _rt()
        mgr = rt.maxOps.GetCurRenderElementMgr(0)
        if mgr is None:
            return None
        # find or add a VRayZDepth element
        zel = None
        for i in range(int(rt.execute("(maxOps.GetCurRenderElementMgr 0).NumRenderElements()"))):
            el = mgr.GetRenderElement(i)
            if "zdepth" in str(rt.classOf(el)).lower():
                zel = el
                break
        added = False
        if zel is None:
            zcls = getattr(rt, "VRayZDepth", None)
            if zcls is None:
                return None
            zel = zcls()
            try:
                zel.zdepth_clamp = True
                zel.zdepth_fromCamera = True
            except Exception:
                pass
            mgr.AddRenderElement(zel)
            added = True
        try:
            zel.enabled = True
        except Exception:
            pass

        # render to a bitmap that carries render elements
        if width and height:
            beauty = rt.render(outputSize=rt.Point2(width, height), vfb=False)
        else:
            beauty = rt.render(vfb=False)
        # the element's own bitmap after a render
        zbmp = _try_render_element_bitmap(rt, zel)
        if added:
            try:
                mgr.RemoveRenderElement(zel)
            except Exception:
                pass
        if zbmp is None:
            return None
        arr = _bitmap_to_gray_array(rt, zbmp, np)
        try:
            rt.close(beauty)
        except Exception:
            pass
        return arr
    except Exception:
        return None


def grab_float_luminance(width: int = 0, height: int = 0):
    """Best-effort SCENE-REFERRED (linear, pre-tonemap) luminance from the render, as an
    H×W float array — the basis for EXACT exposure/CCT (vs. the 8-bit-tonemapped path).
    SELF-GATING: returns (lum, True) only when the grabbed pixels actually carry HDR
    values (any channel > 1.0 in 0..1 terms), which means it's genuinely float/scene-
    referred; otherwise returns None so the safe 8-bit path is used. NEVER raises.

    NOTE: this is OFF by default until a live session confirms the VFB channel really is
    linear on this build — reading a display-referred channel as if linear would feed the
    model wrong numbers, which is worse than the honest 8-bit read. See README.
    """
    try:
        import numpy as np
        rt = _rt()
        # HARD SIZE CAP: reading pixels via pymxs getPixels is a per-pixel Python loop, so
        # a full 1080p+ frame would stall for minutes. Exposure/CCT anchors need only a
        # small sample — render at <= FLOAT_MAX_EDGE on the long side.
        FLOAT_MAX_EDGE = 256
        if not (width and height):
            width, height = FLOAT_MAX_EDGE, int(FLOAT_MAX_EDGE * 3 / 4)
        long_edge = max(width, height)
        if long_edge > FLOAT_MAX_EDGE:
            s = FLOAT_MAX_EDGE / long_edge
            width, height = max(1, int(width * s)), max(1, int(height * s))
        bmp = rt.render(outputSize=rt.Point2(width, height), vfb=False)
        w, h = int(bmp.width), int(bmp.height)
        rows = []
        for y in range(h):
            px = rt.getPixels(bmp, rt.Point2(0, y), w)
            row = np.empty((w, 3), dtype=np.float64)
            for x in range(w):
                c = px[x]
                row[x, 0] = float(c.r) / 255.0
                row[x, 1] = float(c.g) / 255.0
                row[x, 2] = float(c.b) / 255.0
            rows.append(row)
        try:
            rt.close(bmp)
        except Exception:
            pass
        rgb = np.stack(rows, axis=0)  # H×W×3, ~linear 0..(>1 for HDR)
        if float(rgb.max()) <= 1.0001:
            return None  # clamped/8-bit — not genuinely float; use the safe path
        lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
        return lum, True
    except Exception:
        return None


def grab_depth_evidence(width: int = 0, height: int = 0):
    """Best-effort CINEMATIC-DEPTH pair for engine.depth_text: render once with a
    VRayZDepth element and return (lum, z) as same-shape H×W float arrays — lum is the
    beauty's luminance (0..1), z is the depth (larger = farther). Both are read from
    saved PNGs (PIL 'L'/'F'), so no slow per-pixel loop. Returns None on ANY failure, so
    depth simply degrades to absent — it must never feed the model wrong numbers.

    Capped small on the long edge: depth structure (bands / separation / haze) is a
    statistical read, so a downscaled pass is plenty and keeps the extra render cheap.
    """
    try:
        import numpy as np
        rt = _rt()
        DEPTH_MAX_EDGE = 512
        if not (width and height):
            width, height = DEPTH_MAX_EDGE, int(DEPTH_MAX_EDGE * 3 / 4)
        long_edge = max(width, height)
        if long_edge > DEPTH_MAX_EDGE:
            s = DEPTH_MAX_EDGE / long_edge
            width, height = max(1, int(width * s)), max(1, int(height * s))

        mgr = rt.maxOps.GetCurRenderElementMgr(0)
        if mgr is None:
            return None
        zel, added = None, False
        for i in range(int(rt.execute("(maxOps.GetCurRenderElementMgr 0).NumRenderElements()"))):
            el = mgr.GetRenderElement(i)
            if "zdepth" in str(rt.classOf(el)).lower():
                zel = el
                break
        if zel is None:
            zcls = getattr(rt, "VRayZDepth", None)
            if zcls is None:
                return None
            zel = zcls()
            try:
                zel.zdepth_clamp = True
                zel.zdepth_fromCamera = True
            except Exception:
                pass
            mgr.AddRenderElement(zel)
            added = True
        try:
            zel.enabled = True
        except Exception:
            pass

        beauty = rt.render(outputSize=rt.Point2(width, height), vfb=False)
        zbmp = _try_render_element_bitmap(rt, zel)
        if added:
            try:
                mgr.RemoveRenderElement(zel)
            except Exception:
                pass
        if zbmp is None:
            try:
                rt.close(beauty)
            except Exception:
                pass
            return None
        lum = _bitmap_to_lum_array(rt, beauty, np)   # closes `beauty`
        z = _bitmap_to_gray_array(rt, zbmp, np)
        if lum.shape != z.shape:
            return None  # size mismatch → unusable; skip depth
        return lum, z
    except Exception:
        return None


def _try_render_element_bitmap(rt, zel):
    for attr in ("bitmap", "renderbitmap"):
        b = None
        try:
            b = getattr(zel, attr)
        except Exception:
            b = None
        if b is not None:
            return b
    return None


def _bitmap_to_gray_array(rt, bmp, np):
    """Read a Max bitmap into an H×W float array via its saved PNG (grayscale = depth)."""
    img = _bitmap_to_pil(rt, bmp)
    g = img.convert("F")  # 32-bit float grayscale
    return np.asarray(g, dtype=np.float64)


def _bitmap_to_lum_array(rt, bmp, np):
    """Read a Max bitmap (the beauty) into an H×W LUMINANCE array 0..1 via its saved PNG.
    PIL 'L' is ITU-R 601 luma; /255 puts it in the same 0..1 space depth_evidence expects."""
    img = _bitmap_to_pil(rt, bmp)
    return np.asarray(img.convert("L"), dtype=np.float64) / 255.0
