"""
image_parser.py — OCR extraction from images using pytesseract.

Supported formats: JPEG, PNG, TIFF, BMP, HEIC (with conversion), WebP, PDF pages
No external API calls — all local tesseract OCR.

For complex/unclear documents, use PlugOps vision tool (plugops/tools/vision.py)
which routes to Claude's vision API for higher accuracy.
"""

import io
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger("irs_forms_export.parsers.image")

_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp", ".gif"}


def ocr_available() -> bool:
    """Return True if tesseract + pytesseract are both available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _load_image(source: Union[str, Path, bytes, "Image"]) -> "Image":
    """Load image from file path, bytes, or PIL Image object."""
    from PIL import Image

    if isinstance(source, (str, Path)):
        path = Path(source)
        # Handle HEIC (iPhone photos)
        if path.suffix.lower() == ".heic":
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                raise ImportError(
                    "image_parser: HEIC files need pillow-heif — run: pip install pillow-heif"
                )
        return Image.open(path)
    elif isinstance(source, bytes):
        return Image.open(io.BytesIO(source))
    elif hasattr(source, "save"):  # Already a PIL Image
        return source
    else:
        raise TypeError(f"image_parser: unsupported source type: {type(source)}")


def _preprocess_image(img: "Image") -> "Image":
    """
    Preprocess image for better OCR accuracy on tax documents.
    - Convert to grayscale
    - Increase contrast (tax forms have light gray backgrounds)
    - Resize if too small
    """
    from PIL import Image, ImageFilter, ImageEnhance

    # Convert to RGB first if needed (handles RGBA, palette modes)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Convert to grayscale
    img = img.convert("L")

    # Increase resolution if image is small (< 1000px wide)
    if img.width < 1000:
        scale = 1000 / img.width
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Enhance contrast for tax forms (light gray text on white)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)

    # Sharpen slightly
    img = img.filter(ImageFilter.SHARPEN)

    return img


def _run_ocr(img: "Image", lang: str = "eng") -> str:
    """Run pytesseract OCR on preprocessed image."""
    import pytesseract

    # PSM 6: Assume a single uniform block of text — good for tax forms
    # PSM 3: Fully automatic page segmentation — better for complex layouts
    configs = [
        "--psm 6 --oem 3",   # Single block — try first for forms
        "--psm 3 --oem 3",   # Automatic — fallback for complex docs
    ]

    best_text = ""
    for config in configs:
        try:
            text = pytesseract.image_to_string(img, lang=lang, config=config)
            if len(text.strip()) > len(best_text.strip()):
                best_text = text
        except Exception as e:
            logger.debug(f"image_parser: OCR config {config} failed: {e}")

    return best_text


def parse_image_bytes(image_bytes: bytes, *, filename: str = "",
                      preprocess: bool = True) -> dict:
    """
    OCR an image from raw bytes.

    Returns:
        {
            "text": "extracted text...",
            "source": "pytesseract",
            "filename": "...",
            "confidence_hint": float  # crude estimate based on text length
        }
    """
    if not ocr_available():
        raise RuntimeError(
            "image_parser: pytesseract / tesseract not available. "
            "Install: brew install tesseract && pip install pytesseract"
        )

    try:
        img = _load_image(image_bytes)
        if preprocess:
            img = _preprocess_image(img)
        text = _run_ocr(img)

        # Crude confidence: longer text from a small image = probably worked
        confidence = min(len(text.strip()) / 500.0, 1.0)

        return {
            "text": text,
            "source": "pytesseract",
            "filename": filename,
            "confidence_hint": round(confidence, 2),
            "image_size": f"{img.width}x{img.height}",
        }
    except Exception as e:
        logger.error(f"image_parser: failed to OCR image: {e}")
        return {
            "text": "",
            "source": "pytesseract",
            "filename": filename,
            "confidence_hint": 0.0,
            "error": str(e),
        }


def parse_image(path: Union[str, Path], *, preprocess: bool = True) -> dict:
    """
    OCR an image file by path. Returns same format as parse_image_bytes.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"image_parser: file not found: {path}")
    if path.suffix.lower() not in _SUPPORTED_EXTENSIONS | {".heic"}:
        raise ValueError(
            f"image_parser: unsupported image format: {path.suffix}. "
            f"Supported: {', '.join(_SUPPORTED_EXTENSIONS | {'.heic'})}"
        )

    return parse_image_bytes(path.read_bytes(),
                              filename=path.name,
                              preprocess=preprocess)
