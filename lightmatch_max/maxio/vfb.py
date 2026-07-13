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
