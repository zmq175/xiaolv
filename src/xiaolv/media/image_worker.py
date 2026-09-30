"""Dedicated decoder process. No application configuration or credentials are imported."""

import io
import json
import resource
import sys
import warnings


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 16_000_000
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("input limit")
    with Image.open(io.BytesIO(raw)) as check:
        expected = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "WEBP": "image/webp",
            "GIF": "image/gif",
        }
        if check.format not in expected or expected[check.format] != sys.argv[1]:
            raise ValueError("format mismatch")
        width, height = check.size
        if width * height > 16_000_000 or max(width, height) > 16384 or min(width, height) <= 0:
            raise ValueError("pixel limit")
        check.verify()
    with Image.open(io.BytesIO(raw)) as original:
        frames = getattr(original, "n_frames", 1)
        original.seek(0)
        original.load()
        oriented = ImageOps.exif_transpose(original)
        oriented.thumbnail((512, 512), Image.Resampling.LANCZOS)
        rgba = oriented.convert("RGBA")
        output = Image.new("RGB", rgba.size, "white")
        output.paste(rgba, mask=rgba.getchannel("A"))
        encoded = io.BytesIO()
        output.save(encoded, format="JPEG", quality=85)
        result = encoded.getvalue()
        if len(result) > 1024 * 1024:
            raise ValueError("output limit")
        header = json.dumps(
            {"width": output.width, "height": output.height, "frames": frames}
        ).encode()
        sys.stdout.buffer.write(header + b"\n" + result)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - parent receives only a failure status, never image metadata
        sys.exit(1)
