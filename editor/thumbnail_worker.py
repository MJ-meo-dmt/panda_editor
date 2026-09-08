from __future__ import annotations

import math
import sys
from pathlib import Path

from panda3d.core import AmbientLight, DirectionalLight, Filename, LColor, Point3, Vec3, loadPrcFileData

def render_thumbnail(model_path: Path, output_path: Path) -> int:
    loadPrcFileData('', '\n'.join([
        'window-type offscreen', 'win-size 320 200', 'framebuffer-alpha 1',
        'audio-library-name null', 'sync-video false', 'show-frame-rate-meter false']))
    try:
        import panda3d_gltf  # noqa: F401
    except Exception:
        pass
    from direct.showbase.ShowBase import ShowBase
    base = ShowBase(windowType='offscreen')
    base.setBackgroundColor(0.035, 0.055, 0.075, 1)
    model = base.loader.loadModel(Filename.fromOsSpecific(str(model_path)))
    if model is None or model.isEmpty():
        base.destroy(); return 3
    model.reparentTo(base.render)
    bounds = model.getTightBounds()
    if bounds and len(bounds) == 2:
        lo, hi = bounds; center = (lo + hi) * 0.5; dims = hi - lo
        radius = max(0.25, float(max(abs(dims.x), abs(dims.y), abs(dims.z))) * 0.65)
    else:
        center = Point3(0,0,0); radius = 1.5
    amb=AmbientLight('thumb-ambient'); amb.setColor(LColor(.55,.58,.62,1)); amb_np=base.render.attachNewNode(amb); base.render.setLight(amb_np)
    sun=DirectionalLight('thumb-key'); sun.setColor(LColor(.9,.92,1,1)); sun_np=base.render.attachNewNode(sun); sun_np.setHpr(-35,-45,0); base.render.setLight(sun_np)
    base.camLens.setFov(35); base.camLens.setNearFar(0.01, max(1000.0, radius*100.0))
    dist=radius/max(0.15,math.tan(math.radians(35/2)))*1.3
    base.camera.setPos(center+Vec3(dist*.72,-dist,dist*.55)); base.camera.lookAt(center)
    base.graphicsEngine.renderFrame(); base.graphicsEngine.renderFrame()
    img=base.win.getScreenshot(); output_path.parent.mkdir(parents=True,exist_ok=True)
    ok=img.write(Filename.fromOsSpecific(str(output_path)))
    model.removeNode(); base.destroy(); return 0 if ok else 4

if __name__=='__main__':
    if len(sys.argv)!=3: raise SystemExit(2)
    raise SystemExit(render_thumbnail(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()))
