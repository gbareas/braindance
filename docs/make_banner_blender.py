"""Renders docs/banner.jpg with Blender: an original neon scene (glowing title,
perspective grid, a measured curve with its fit). Run with Blender's Python:

    blender -b -P docs/make_banner_blender.py
    # or, with the bpy module from PyPI (Python 3.11): pip install bpy==4.2.0 numpy pillow
    python docs/make_banner_blender.py

Uses Cycles on the CPU, so no GPU is needed. Takes a few minutes.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
OUT_RAW = HERE / "banner_raw.png"
OUT = HERE / "banner.jpg"
W, H, SAMPLES = 1600, 420, 64
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CYAN, MAGENTA, YELLOW = (0.0, 0.85, 1.0), (1.0, 0.05, 0.55), (1.0, 0.8, 0.1)
rng = np.random.default_rng(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def emission(name, colour, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*colour, 1)
    e.inputs["Strength"].default_value = strength
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    return m


def dark_metal(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.02, 0.02, 0.04, 1)
    b.inputs["Metallic"].default_value = 0.9
    b.inputs["Roughness"].default_value = 0.25
    return m


# world
world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.006, 0.003, 0.015, 1)
scene.world = world

# grid floor: a subdivided plane drawn as glowing wires
bpy.ops.mesh.primitive_grid_add(x_subdivisions=60, y_subdivisions=60, size=120, location=(0, 40, 0))
grid = bpy.context.object
wire = grid.modifiers.new("wire", "WIREFRAME")
wire.thickness = 0.04
grid.data.materials.append(emission("grid", MAGENTA, 1.2))

# title: a dark metal body with a glowing bevel, and a magenta ghost behind it
def text(body, size, loc, extrude=0.0, bevel=0.0, mats=()):
    bpy.ops.object.text_add(location=loc, rotation=(math.radians(90), 0, 0))
    t = bpy.context.object
    t.data.body = body
    t.data.font = bpy.data.fonts.load(FONT)
    t.data.size = size
    t.data.align_x = "CENTER"
    t.data.align_y = "CENTER"
    t.data.extrude = extrude
    t.data.bevel_depth = bevel
    for m in mats:
        t.data.materials.append(m)
    return t


title = text("BRAINDANCE", 3.2, (0, 0, 3.4), extrude=0.25, bevel=0.035,
             mats=(dark_metal("body"), emission("edge", CYAN, 8.0)))
# after converting to a mesh: material 0 on the letter faces, 1 on the bevel and sides
bpy.context.view_layer.objects.active = title
bpy.ops.object.convert(target="MESH")
title = bpy.context.object
for poly in title.data.polygons:
    poly.material_index = 0 if abs(poly.normal.z) > 0.95 else 1  # local z: the letter faces
ghost = text("BRAINDANCE", 3.2, (0.18, 0.6, 3.45), mats=(emission("ghost", MAGENTA, 1.5),))
text("publication-ready figures  //  every plotted value checked against its data", 0.46, (0, -0.3, 1.2),
     mats=(emission("sub", CYAN, 3.0),))

# a measured curve with its fit, floating behind the title
x = np.linspace(0, 1, 160)
fit = 0.55 + 0.32 * np.sin(2 * np.pi * (1.3 * x + 0.1)) * np.exp(-1.1 * x)
X, Z = -13 + 26 * x, 1.9 + 3.0 * fit
curve = bpy.data.curves.new("fit", "CURVE")
curve.dimensions = "3D"
curve.bevel_depth = 0.04
sp = curve.splines.new("POLY")
sp.points.add(len(x) - 1)
for p, xi, zi in zip(sp.points, X, Z):
    p.co = (xi, 3.0, zi, 1)
cobj = bpy.data.objects.new("fit", curve)
scene.collection.objects.link(cobj)
curve.materials.append(emission("fitmat", CYAN, 5.0))
pts = emission("pts", YELLOW, 5.0)
for xi, zi in zip(X[::6], Z[::6]):
    bpy.ops.mesh.primitive_torus_add(major_radius=0.13, minor_radius=0.035, location=(xi, 3.0, zi + rng.normal(0, 0.12)),
                                     rotation=(math.radians(90), 0, 0))
    bpy.context.object.data.materials.append(pts)

# camera
bpy.ops.object.camera_add(location=(0, -17, 3.6), rotation=(math.radians(86), 0, 0))
cam = bpy.context.object
cam.data.lens = 32
scene.camera = cam

# render
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Punchy"

# compositor: bloom and a little chromatic aberration
scene.use_nodes = True
nt = scene.node_tree
nt.nodes.clear()
rl = nt.nodes.new("CompositorNodeRLayers")
glare = nt.nodes.new("CompositorNodeGlare")
glare.glare_type = "FOG_GLOW"
glare.quality = "HIGH"
glare.size = 8
glare.mix = -0.4
lens = nt.nodes.new("CompositorNodeLensdist")
lens.inputs["Dispersion"].default_value = 0.02
comp = nt.nodes.new("CompositorNodeComposite")
nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
nt.links.new(glare.outputs["Image"], lens.inputs["Image"])
nt.links.new(lens.outputs["Image"], comp.inputs["Image"])

scene.render.filepath = str(OUT_RAW)
bpy.ops.render.render(write_still=True)

# scanlines and vignette, then JPEG
from PIL import Image  # noqa: E402

img = np.asarray(Image.open(OUT_RAW).convert("RGB"), dtype=np.float32)
img *= np.where(np.arange(H)[:, None, None] % 3 == 0, 0.8, 1.0)
yy, xx = np.mgrid[0:H, 0:W]
img *= (1 - 0.35 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2)[..., None]
Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(OUT, quality=90, optimize=True)
OUT_RAW.unlink()
print(OUT, file=sys.stderr)
