"""
Filters module contains functions for applying filters to frames
before posting them as random posts.

Ported from py-rafasx/rand-frame and adapted to the frame-poster layout.
The palette filter and the variable-offset mirror are ports from
alefouau/ehtfio_random.
"""

from pathlib import Path
from random import choices, randint

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from src.logger import get_logger
from src.paths import project_path

# Define output directory for processed images
OUTPUT_DIR = project_path("images")

# Fixed height (in pixels) of the color palette strip generated below frames
PALETTE_STRIP_HEIGHT = 50

logger = get_logger(__name__)


def none_filter(frame_path: Path) -> Path:
    """Returns the original frame without applying any filter."""
    return frame_path


def two_panels(frame_path1: Path, frame_path2: Path) -> Path | None:
    """Stacks two frames vertically into a single image."""
    try:
        with Image.open(frame_path1) as img1, Image.open(frame_path2) as img2:
            image_width, image_height = img1.size
            img3 = Image.new("RGB", (image_width, image_height * 2))
            img3.paste(img1, (0, 0))
            img3.paste(img2, (0, image_height))

        return _save_output(img3, "_two_panels.jpg")
    except OSError as e:
        logger.error("IOError while processing two-panels image: %s", e)
        return None


def mirror(frame_path: Path) -> Path | None:
    """Mirrors a slice of the image with a random seam position.

    The right half is cropped starting at a random offset between 50% and
    100% of the half width (port of ehtfio_random's mirror_image), then
    flopped and appended, producing a kaleidoscope effect whose seam slides
    across the frame instead of always splitting it in the middle.
    """
    try:
        with Image.open(frame_path) as img:
            width, height = img.size
            half_width = width // 2
            # clamp so the crop never exceeds the right edge (no black bars)
            offset_pixels = half_width * randint(50, 100) // 100

            sliver = img.crop((offset_pixels, 0, offset_pixels + half_width, height))
            mirrored_sliver = sliver.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            output_img = Image.new("RGB", (width, height))
            output_img.paste(mirrored_sliver, (0, 0))
            output_img.paste(sliver, (half_width, 0))

        return _save_output(output_img, "_mirror.jpg")
    except OSError as e:
        logger.error("IOError while processing mirror image: %s", e)
        return None


def brightness_contrast(
    frame_path: Path, brightness: float = 0.8, contrast: float = 1.5
) -> Path | None:
    """Applies a brightness and contrast filter to an image."""
    input_path = Path(frame_path)

    if not input_path.exists():
        logger.error("brightness_contrast: file not found at %s", frame_path)
        return None

    try:
        with Image.open(input_path) as img:
            img = ImageEnhance.Brightness(img).enhance(brightness)
            img = ImageEnhance.Contrast(img).enhance(contrast)

        return _save_output(img, "_brightness_contrast.jpg")
    except OSError as e:
        logger.error("IOError while processing brightness/contrast image: %s", e)
        return None


def negative(frame_path: Path) -> Path | None:
    """Applies a negative filter."""
    try:
        with Image.open(frame_path) as img:
            output_img = img.convert("RGB").point(lambda x: 255 - x)

        return _save_output(output_img, "_negative.jpg")
    except OSError as e:
        logger.error("IOError while processing negative image: %s", e)
        return None


def palette_filter(frame_path: Path) -> Path | None:
    """Builds a color palette strip and appends it below the frame.

    Port of ehtfio_random's generate_palette: quantizes the frame to a
    random number of colors (6-10), sorts the palette by perceived
    brightness (brightest first), renders one labeled block per color
    (hex code written in white/black depending on the block brightness)
    and stacks the strip under the original image.
    """
    num_colors = randint(6, 10)

    try:
        with Image.open(frame_path) as img:
            rgb_img = img.convert("RGB")
            width, height = rgb_img.size

            # sample a small copy so quantization stays fast on big frames
            small = rgb_img.resize((100, 100))
            quantized = small.quantize(colors=num_colors, dither=Image.Dither.NONE)

            raw_palette = quantized.getpalette() or []
            colors = [tuple(raw_palette[i : i + 3]) for i in range(0, num_colors * 3, 3)]

        def brightness(color: tuple[int, int, int]) -> int:
            r, g, b = color
            return (299 * r + 587 * g + 114 * b) // 1000

        # brightest first, matching the original sort -rn behavior
        colors.sort(key=brightness, reverse=True)

        block_width = max(width // num_colors, 20)
        font = ImageFont.load_default(size=23)

        strip = Image.new("RGB", (block_width * num_colors, PALETTE_STRIP_HEIGHT))
        draw = ImageDraw.Draw(strip)

        for index, color in enumerate(colors):
            hex_label = "#{:02X}{:02X}{:02X}".format(*color)
            text_color = "white" if brightness(color) < 128 else "black"

            box = (index * block_width, 0, (index + 1) * block_width, PALETTE_STRIP_HEIGHT)
            draw.rectangle(box, fill=color)
            draw.text(
                (index * block_width + block_width // 2, PALETTE_STRIP_HEIGHT // 2),
                hex_label,
                fill=text_color,
                font=font,
                anchor="mm",
            )

        output_img = Image.new("RGB", (width, height + PALETTE_STRIP_HEIGHT))
        output_img.paste(rgb_img, (0, 0))
        output_img.paste(strip.crop((0, 0, width, PALETTE_STRIP_HEIGHT)), (0, height))

        return _save_output(output_img, "_palette.jpg")
    except OSError as e:
        logger.error("IOError while processing palette image: %s", e)
        return None


def _warp(frame_path: Path, factor: float, filename: str) -> Path | None:
    """Helper to apply radial warp (implode/explode) via coordinates remapping.

    Port of ImageMagick's -implode filter using Pillow's native MESH transform.
    """
    try:
        with Image.open(frame_path) as img:
            rgb_img = img.convert("RGB")
            width, height = rgb_img.size

            grid_cols = 40
            grid_rows = 30

            dw = width / grid_cols
            dh = height / grid_rows

            center_x, center_y = width / 2.0, height / 2.0
            max_r = min(center_x, center_y)

            # Map coordinates (x, y) relative to center using ImageMagick formula:
            # source_r = r * (1 + factor * (1 - r / max_r) ** 2)
            def warp_point(x: float, y: float) -> tuple[float, float]:
                dx = x - center_x
                dy = y - center_y
                d = (dx * dx + dy * dy) ** 0.5
                if 0 < d < max_r:
                    d_norm = d / max_r
                    source_d = d * (1.0 + factor * (1.0 - d_norm) ** 2)
                    ratio = source_d / d
                    return center_x + dx * ratio, center_y + dy * ratio
                return x, y

            # Precompute grid intersection warp points
            grid_points = {}
            for r in range(grid_rows + 1):
                for c in range(grid_cols + 1):
                    grid_points[(c, r)] = warp_point(c * dw, r * dh)

            mesh = []
            for r in range(grid_rows):
                for c in range(grid_cols):
                    target_box = (
                        int(c * dw),
                        int(r * dh),
                        int((c + 1) * dw),
                        int((r + 1) * dh),
                    )
                    # Quads corners ordering: top-left, bottom-left, bottom-right, top-right
                    q0 = grid_points[(c, r)]
                    q1 = grid_points[(c, r + 1)]
                    q2 = grid_points[(c + 1, r + 1)]
                    q3 = grid_points[(c + 1, r)]

                    quad = (
                        q0[0],
                        q0[1],
                        q1[0],
                        q1[1],
                        q2[0],
                        q2[1],
                        q3[0],
                        q3[1],
                    )
                    mesh.append((target_box, quad))

            # Remap using native C bilinear interpolation
            output_img = rgb_img.transform(
                (width, height), Image.Transform.MESH, mesh, resample=Image.Resampling.BILINEAR
            )

        return _save_output(output_img, filename)
    except Exception as e:
        logger.error("Error applying warp (factor=%s): %s", factor, e)
        return None


def warp_in(frame_path: Path) -> Path | None:
    """Applies an implode filter (warp pixels inward)."""
    factor = randint(1, 7) / 10.0
    return _warp(frame_path, factor, "_warp_in.jpg")


def warp_out(frame_path: Path) -> Path | None:
    """Applies an explode filter (warp pixels outward)."""
    factor = -randint(1, 7) / 10.0
    return _warp(frame_path, factor, "_warp_out.jpg")


def _save_output(img: Image.Image, filename: str) -> Path | None:
    """Save a processed image inside OUTPUT_DIR and return its path."""
    output_path = OUTPUT_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    logger.info("Saved filtered image to %s", output_path)
    return output_path


filter_registry = {
    "none_filter": none_filter,
    "two_panels": two_panels,
    "mirror": mirror,
    "negative": negative,
    "brightness_contrast": brightness_contrast,
    "palette_filter": palette_filter,
    "warp_in": warp_in,
    "warp_out": warp_out,
}


def apply_filter(filter_func, framedata: list[dict]) -> Path | None:
    """Apply a filter to one or two frames and return the resulting image path.

    Args:
        filter_func: A callable from ``filter_registry``.
        framedata: List with one dict (single frame) or two dicts (two panels),
            each containing a "frame_path" key.

    Returns:
        Path to the processed image, or None on failure.
    """
    if not isinstance(framedata, list) or not all(isinstance(item, dict) for item in framedata):
        logger.error("Invalid framedata format for apply_filter")
        return None

    try:
        if len(framedata) == 2 and all("frame_path" in item for item in framedata):
            output_path = filter_func(framedata[0]["frame_path"], framedata[1]["frame_path"])
        elif len(framedata) == 1 and "frame_path" in framedata[0]:
            output_path = filter_func(framedata[0]["frame_path"])
        else:
            logger.error("Invalid framedata structure or missing keys")
            return None
    except Exception as e:
        logger.error("Error applying filter %s: %s", getattr(filter_func, "__name__", "?"), e)
        return None

    if not output_path:
        logger.error("Failed to apply filter %s", getattr(filter_func, "__name__", "?"))
        return None

    return output_path


def select_filter(config):
    """Select an enabled filter based on the "filters" config section and their weights.

    Falls back to ``none_filter`` when the section is missing or empty.
    """
    active_filters = {}

    for filter_name, settings in config.get("filters", {}).items():
        if isinstance(settings, dict) and settings.get("enabled", False):
            active_filters[filter_name] = settings.get("percent", 0)

    if not active_filters:
        return filter_registry["none_filter"]

    selected = choices(
        list(active_filters.keys()),
        weights=list(active_filters.values()),
        k=1,
    )[0]

    return filter_registry[selected]
