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
