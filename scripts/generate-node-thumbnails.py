"""Regenerate the node thumbnail atlas. Requires Pillow, wgpu, numpy and onnxruntime.

Usage: python scripts/generate-node-thumbnails.py /path/to/u2netp.onnx
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import numpy as np
import onnxruntime
from PIL import Image
import wgpu

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "apps/open_quartz_video_editor"
ASSETS = EDITOR / "ui/node-thumbnails"
SIZE = 128
COLUMNS = 8

VERTEX = """
struct VertexOut {
    @builtin(position) position: vec4f,
    @location(0) uv: vec2f,
}
@vertex fn thumbnail_vertex(@builtin(vertex_index) index: u32) -> VertexOut {
    let uv = array<vec2f, 3>(vec2f(0, 0), vec2f(2, 0), vec2f(0, 2))[index];
    return VertexOut(vec4f(uv * vec2f(2, -2) + vec2f(-1, 1), 0, 1), uv);
}
"""

# Representative settings keep the previews readable at tile size.
UNIFORMS = {
    "Custom Shader": (0.76,),
    "Blend": (0.40,),
    "Luma Mask": (1.0,),
    "Color Corrector": (0.07, 1.24),
    "Brightness/Contrast": (0.08, 1.23),
    "Hue Rotate": (1.5,),
    "Threshold": (0.46,),
    "Sobel Edge Detection": (1.75,),
    "Sharpen": (1.3,),
    "Pixelate": ((11.0, 11.0),),
    "Twirl": (0.65, 3.8),
    "Ripple": (22.0, 0.045),
    "Displacement": (0.35,),
    "Barrel": (0.85, 0.45),
    "Pinch": (0.64, 0.80),
}


class ThumbnailRenderer:
    def __init__(self):
        self.device = wgpu.gpu.request_adapter_sync().request_device_sync()
        self.sampler = self.device.create_sampler(mag_filter="linear", min_filter="linear")

    def texture(self, image):
        width, height = image.size
        texture = self.device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )
        self.device.queue.write_texture(
            {"texture": texture}, image.convert("RGBA").tobytes(),
            {"bytes_per_row": width * 4}, (width, height, 1),
        )
        return texture.create_view()

    def render(self, code, textures, uniforms):
        device = self.device
        shader = device.create_shader_module(code=VERTEX + code)
        pipeline = device.create_render_pipeline(
            layout="auto",
            vertex={"module": shader, "entry_point": "thumbnail_vertex"},
            fragment={"module": shader, "entry_point": "main", "targets": [{"format": "rgba8unorm"}]},
        )
        resources = {}
        for index, texture in enumerate(textures):
            resources[index * 2] = texture
            resources[index * 2 + 1] = self.sampler
        for index, value in enumerate(uniforms, start=len(textures) * 2):
            components = value if isinstance(value, tuple) else (value,)
            buffer = device.create_buffer_with_data(
                data=struct.pack(f"<{len(components)}f", *components), usage=wgpu.BufferUsage.UNIFORM,
            )
            resources[index] = {"buffer": buffer}
        bind_group = device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": index, "resource": resource} for index, resource in resources.items()],
        )
        target = device.create_texture(
            size=(SIZE, SIZE, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
        )
        encoder = device.create_command_encoder()
        render_pass = encoder.begin_render_pass(color_attachments=[{
            "view": target.create_view(), "load_op": "clear", "store_op": "store",
            "clear_value": (0, 0, 0, 0),
        }])
        render_pass.set_pipeline(pipeline)
        render_pass.set_bind_group(0, bind_group)
        render_pass.draw(3)
        render_pass.end()
        device.queue.submit([encoder.finish()])
        pixels = device.queue.read_texture({"texture": target}, {"bytes_per_row": SIZE * 4}, (SIZE, SIZE, 1))
        return Image.frombytes("RGBA", (SIZE, SIZE), bytes(pixels))


def portrait_matte(portrait, model_path):
    model = Path(model_path).read_bytes()
    if hashlib.sha256(model).hexdigest() != "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8":
        raise ValueError("Expected the U2Net-P ONNX model used by Person Matte")
    session = onnxruntime.InferenceSession(model, providers=["CPUExecutionProvider"])
    sample = np.asarray(portrait.resize((320, 320)), dtype=np.float32) / 255.0
    mask = session.run(["1959"], {session.get_inputs()[0].name: sample.transpose(2, 0, 1)[None]})[0].squeeze()
    mask = Image.fromarray(np.uint8(np.clip(mask, 0, 1) * 255)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    tile = portrait.resize((SIZE, SIZE), Image.Resampling.LANCZOS).convert("RGBA")
    tile.putalpha(mask)
    return tile


def on_checkerboard(tile):
    y, x = np.indices((SIZE, SIZE))
    checks = np.where((x // 12 + y // 12) % 2, 54, 82).astype(np.uint8)
    background = Image.fromarray(checks).convert("RGBA")
    return Image.alpha_composite(background, tile).convert("RGB")


def main(model_path):
    renderer = ThumbnailRenderer()
    landscape = Image.open(ASSETS / "landscape.jpg").convert("RGB")
    portrait = Image.open(ASSETS / "portrait.jpg").convert("RGB")
    source = renderer.texture(landscape.resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    # A second branch from the same still gives compositors non-identical inputs.
    alternate = renderer.texture(landscape.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                                 .resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    catalog = json.loads((ROOT / "crates/open_quartz/src/project/shader_catalog.json").read_text(encoding="utf-8"))
    presets = {group["category"]: group["items"] for group in catalog["groups"]}
    composites = (EDITOR / "src/clip_pipeline.rs").read_text(encoding="utf-8")

    def shader(label, code, textures=(source,)):
        print(label)
        return renderer.render(code, textures, UNIFORMS.get(label, ()))

    tiles = {
        "Custom Shader": shader("Custom Shader", presets["CUSTOM"][0]["code"]),
        "Person Matte": portrait_matte(portrait, model_path),
    }
    for label, constant in [("Blend", "BLEND_CODE"), ("Luma Mask", "MASK_CODE")]:
        code = re.search(rf'const {constant}: &str = r#"(.*?)"#;', composites, re.S)[1]
        tiles[label] = shader(label, code, (source, alternate))
    # Corrector has neutral defaults. Show an example primary adjustment.
    brightness = next(item["code"] for item in presets["COLOR"] if item["label"] == "Brightness/Contrast")
    tiles["Color Corrector"] = shader("Color Corrector", brightness)
    for category in ("COLOR", "FILTER", "DISTORTION", "BLEND"):
        for item in presets[category]:
            label = item["label"]
            code = item["code"]
            textures = (source, alternate) if category == "BLEND" else (source,)
            if label == "Displacement":
                textures = (alternate, source)
            tiles[label] = shader(label, code, textures)
    atlas = Image.new("RGB", (SIZE * COLUMNS, SIZE * ((len(tiles) + COLUMNS - 1) // COLUMNS)))
    for index, tile in enumerate(tiles.values()):
        atlas.paste(on_checkerboard(tile), (index % COLUMNS * SIZE, index // COLUMNS * SIZE))
    atlas.save(ASSETS / "effects.jpg", quality=92, optimize=True, subsampling=0)
    (ASSETS / "effects.json").write_text(json.dumps(list(tiles), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
