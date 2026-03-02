"""
sdimport extractor — core image generation metadata extraction logic.

Self-contained library module. No CLI code, no sys.exit() calls.
All errors are raised as exceptions for the caller to handle.

Supported sources:
  - Local PNG files (A1111 tEXt/parameters, ComfyUI tEXt/workflow)
  - Civitai image URLs  (https://civitai.com/images/<id>)
  - PromptHero          (https://prompthero.com/prompt/<slug>)
  - Lexica              (https://lexica.art/prompt/<id>)
  - Direct image URLs   (downloads and reads embedded PNG metadata)
"""

from __future__ import annotations

import json
import logging
import os
import re
import struct
import tempfile
import zlib
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Soft dependencies — imported lazily so the module loads without them
# ---------------------------------------------------------------------------

def _require_requests():
    try:
        import requests
        return requests
    except ImportError:
        raise ImportError(
            "The 'requests' package is required for URL extraction. "
            "Install with: pip install requests"
        )


def _require_bs4():
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup
    except ImportError:
        raise ImportError(
            "The 'beautifulsoup4' package is required for page scraping. "
            "Install with: pip install beautifulsoup4"
        )


# ---------------------------------------------------------------------------
# Sampler name mapping  (A1111 → ComfyUI)
# ---------------------------------------------------------------------------

SAMPLER_MAP = {
    "Euler":               ("euler",              "normal"),
    "Euler a":             ("euler_ancestral",    "normal"),
    "LMS":                 ("lms",                "normal"),
    "Heun":                ("heun",               "normal"),
    "DPM2":                ("dpm_2",              "normal"),
    "DPM2 a":              ("dpm_2_ancestral",    "normal"),
    "DPM++ 2S a":          ("dpmpp_2s_ancestral", "normal"),
    "DPM++ 2M":            ("dpmpp_2m",           "normal"),
    "DPM++ SDE":           ("dpmpp_sde",          "normal"),
    "DPM++ 2M SDE":        ("dpmpp_2m_sde",       "normal"),
    "DPM fast":            ("dpm_fast",           "normal"),
    "DPM adaptive":        ("dpm_adaptive",       "normal"),
    "LMS Karras":          ("lms",                "karras"),
    "DPM2 Karras":         ("dpm_2",              "karras"),
    "DPM2 a Karras":       ("dpm_2_ancestral",    "karras"),
    "DPM++ 2S a Karras":   ("dpmpp_2s_ancestral", "karras"),
    "DPM++ 2M Karras":     ("dpmpp_2m",           "karras"),
    "DPM++ SDE Karras":    ("dpmpp_sde",          "karras"),
    "DPM++ 2M SDE Karras": ("dpmpp_2m_sde",       "karras"),
    "DDIM":                ("ddim",               "normal"),
    "PLMS":                ("plms",               "normal"),
    "UniPC":               ("uni_pc",             "normal"),
    "Restart":             ("restart",            "normal"),
}


def map_sampler(a1111_name: str) -> tuple:
    """Return (comfyui_sampler, comfyui_scheduler) from an A1111 sampler name."""
    if not a1111_name:
        return "euler", "normal"
    return SAMPLER_MAP.get(a1111_name, (a1111_name.lower().replace(" ", "_"), "normal"))


# ---------------------------------------------------------------------------
# GenParams data class
# ---------------------------------------------------------------------------

class GenParams:
    """Normalized image generation parameters extracted from any source."""

    def __init__(self):
        self.positive    = ""
        self.negative    = ""
        self.model       = ""    # checkpoint filename (best effort)
        self.steps       = 20
        self.cfg         = 7.0
        self.seed        = -1   # -1 = random
        self.sampler     = "euler"
        self.scheduler   = "normal"
        self.width       = 512
        self.height      = 512
        self.source_url  = ""
        self.source_type = ""

    def to_dict(self) -> dict:
        return {
            "positive":    self.positive,
            "negative":    self.negative,
            "model":       self.model,
            "steps":       self.steps,
            "cfg":         self.cfg,
            "seed":        self.seed,
            "sampler":     self.sampler,
            "scheduler":   self.scheduler,
            "width":       self.width,
            "height":      self.height,
            "source_url":  self.source_url,
            "source_type": self.source_type,
        }


# ---------------------------------------------------------------------------
# PNG chunk reader (stdlib only — no Pillow)
# ---------------------------------------------------------------------------

def read_png_text_chunks(path: str) -> dict:
    """Read all tEXt/iTXt chunks from a PNG file. Returns {keyword: text}."""
    chunks = {}
    with open(path, "rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            return chunks
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            length = struct.unpack(">I", header[:4])[0]
            chunk_type = header[4:8].decode("ascii", errors="replace")
            data = f.read(length)
            f.read(4)  # CRC

            if chunk_type == "tEXt":
                try:
                    null_pos = data.index(b"\x00")
                    keyword = data[:null_pos].decode("latin-1")
                    text    = data[null_pos + 1:].decode("latin-1")
                    chunks[keyword] = text
                except Exception:
                    pass

            elif chunk_type == "iTXt":
                try:
                    null_pos = data.index(b"\x00")
                    keyword  = data[:null_pos].decode("latin-1")
                    rest = data[null_pos + 1:]
                    comp_flag = rest[0]
                    rest = rest[2:]                          # skip flag + method
                    rest = rest[rest.index(b"\x00") + 1:]   # skip language
                    rest = rest[rest.index(b"\x00") + 1:]   # skip translated keyword
                    text = (
                        zlib.decompress(rest).decode("utf-8", errors="replace")
                        if comp_flag
                        else rest.decode("utf-8", errors="replace")
                    )
                    chunks[keyword] = text
                except Exception:
                    pass

            if chunk_type == "IEND":
                break
    return chunks


# ---------------------------------------------------------------------------
# Extractor: Local PNG
# ---------------------------------------------------------------------------

def parse_a1111_params(raw: str) -> GenParams:
    """Parse an A1111-format 'parameters' text chunk into GenParams."""
    p = GenParams()
    p.source_type = "PNG/A1111"
    lines = raw.strip().split("\n")

    param_line_idx = next(
        (i for i, l in enumerate(lines) if re.search(r"\bSteps:\s*\d+", l)),
        None,
    )
    if param_line_idx is None:
        p.positive = raw.strip()
        return p

    prompt_lines = lines[:param_line_idx]
    neg_idx = next(
        (i for i, l in enumerate(prompt_lines) if l.startswith("Negative prompt:")),
        None,
    )
    if neg_idx is not None:
        p.positive = "\n".join(prompt_lines[:neg_idx]).strip()
        p.negative = re.sub(
            r"^Negative prompt:\s*", "",
            "\n".join(prompt_lines[neg_idx:]),
            flags=re.IGNORECASE,
        ).strip()
    else:
        p.positive = "\n".join(prompt_lines).strip()

    settings = " ".join(lines[param_line_idx:])

    def grab(pattern, cast=str, default=None):
        m = re.search(pattern, settings, re.IGNORECASE)
        if m:
            try:
                return cast(m.group(1))
            except Exception:
                pass
        return default

    p.steps = grab(r"Steps:\s*(\d+)", int, 20)
    p.cfg   = grab(r"CFG scale:\s*([\d.]+)", float, 7.0)
    p.seed  = grab(r"Seed:\s*(-?\d+)", int, -1)
    p.model = (grab(r"Model:\s*([^,]+)") or "").strip()
    p.sampler, p.scheduler = map_sampler((grab(r"Sampler:\s*([^,]+)") or "").strip())

    sz = re.search(r"Size:\s*(\d+)x(\d+)", settings, re.IGNORECASE)
    if sz:
        p.width, p.height = int(sz.group(1)), int(sz.group(2))

    return p


def extract_from_png(path: str) -> GenParams:
    """Extract generation parameters from a local PNG file."""
    chunks = read_png_text_chunks(path)

    if "workflow" in chunks:
        # ComfyUI PNG — full workflow JSON is embedded verbatim
        p = GenParams()
        p.source_type = "PNG/ComfyUI-workflow"
        p._raw_comfyui_workflow = chunks["workflow"]
        try:
            wf = json.loads(chunks["workflow"])
            for node in wf.values():
                if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                    title = node.get("_meta", {}).get("title", "").lower()
                    text  = node.get("inputs", {}).get("text", "")
                    if "neg" in title:
                        p.negative = text
                    else:
                        p.positive = text
        except Exception:
            pass
        return p

    if "prompt" in chunks:
        p = GenParams()
        p.source_type = "PNG/ComfyUI-prompt"
        p._raw_comfyui_prompt = chunks["prompt"]
        return p

    if "parameters" in chunks:
        return parse_a1111_params(chunks["parameters"])

    p = GenParams()
    p.source_type = "PNG/unknown"
    p.positive = "(no recognized metadata in this PNG)"
    return p


# ---------------------------------------------------------------------------
# Extractor: Civitai
# ---------------------------------------------------------------------------

def extract_from_civitai(url: str) -> GenParams:
    """Extract from a Civitai image URL using the public API."""
    requests = _require_requests()

    m = re.search(r"civitai\.com/images/(\d+)", url)
    if not m:
        raise ValueError(f"Cannot parse Civitai image ID from URL: {url}")

    api_url = f"https://civitai.com/api/v1/images/{m.group(1)}"
    logger.debug(f"[sdimport] Civitai API: {api_url}")

    resp = requests.get(api_url, timeout=15, headers={"User-Agent": "GENESIS-sdimport/1.0"})
    if resp.status_code != 200:
        raise IOError(f"Civitai API returned HTTP {resp.status_code} for {api_url}")

    data = resp.json()
    meta = data.get("meta") or {}

    p = GenParams()
    p.source_type = "Civitai"
    p.source_url  = url
    p.positive    = meta.get("prompt", "") or data.get("title", "")
    p.negative    = meta.get("negativePrompt", "")
    p.steps       = int(meta.get("steps", 20) or 20)
    p.cfg         = float(meta.get("cfgScale", 7.0) or 7.0)
    p.seed        = int(meta.get("seed", -1) or -1)
    p.model       = (meta.get("Model") or meta.get("model") or "").strip()
    p.sampler, p.scheduler = map_sampler((meta.get("sampler", "") or "").strip())

    sz = re.match(r"(\d+)x(\d+)", meta.get("Size", ""))
    if sz:
        p.width, p.height = int(sz.group(1)), int(sz.group(2))

    return p


# ---------------------------------------------------------------------------
# Extractor: PromptHero
# ---------------------------------------------------------------------------

def extract_from_prompthero(url: str) -> GenParams:
    """Extract from a PromptHero prompt page."""
    requests     = _require_requests()
    BeautifulSoup = _require_bs4()

    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        raise IOError(f"PromptHero returned HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    p = GenParams()
    p.source_type = "PromptHero"
    p.source_url  = url

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            if isinstance(ld, list):
                ld = ld[0]
            if ld.get("description"):
                p.positive = ld["description"]
                break
        except Exception:
            pass

    if not p.positive:
        og = soup.find("meta", property="og:description")
        if og:
            p.positive = og.get("content", "")

    if not p.positive:
        for sel in [".prompt-text", ".prompt", "[data-prompt]", "pre"]:
            el = soup.select_one(sel)
            if el:
                p.positive = el.get_text(strip=True)
                break

    neg_section = soup.find(string=re.compile(r"negative prompt", re.IGNORECASE))
    if neg_section and neg_section.parent:
        sib = neg_section.parent.find_next_sibling()
        if sib:
            p.negative = sib.get_text(strip=True)

    page_text = soup.get_text()

    def grab(pattern, cast=str, default=None):
        m = re.search(pattern, page_text, re.IGNORECASE)
        if m:
            try:
                return cast(m.group(1))
            except Exception:
                pass
        return default

    p.steps = grab(r"steps[:\s]+(\d+)", int) or 20
    p.cfg   = grab(r"cfg[:\s]+([\d.]+)", float) or 7.0
    p.seed  = grab(r"seed[:\s]+(-?\d+)", int) or -1
    p.model = (grab(r"model[:\s]+([^\n,]+)") or "").strip()

    return p


# ---------------------------------------------------------------------------
# Extractor: Lexica
# ---------------------------------------------------------------------------

def extract_from_lexica(url: str) -> GenParams:
    """Extract from a Lexica prompt page, trying the API first."""
    requests      = _require_requests()
    BeautifulSoup = _require_bs4()

    m = re.search(r"lexica\.art/prompt/([a-zA-Z0-9_-]+)", url)
    if m:
        try:
            resp = requests.get(
                f"https://lexica.art/api/v1/search?q=id:{m.group(1)}",
                timeout=10,
                headers={"User-Agent": "GENESIS-sdimport/1.0"},
            )
            if resp.status_code == 200:
                imgs = resp.json().get("images", [])
                if imgs:
                    img = imgs[0]
                    p = GenParams()
                    p.source_type = "Lexica"
                    p.source_url  = url
                    p.positive    = img.get("prompt", "")
                    p.negative    = img.get("negativePrompt", "")
                    p.cfg         = float(img.get("guidance", 7.0) or 7.0)
                    p.seed        = int(img.get("seed", -1) or -1)
                    p.width       = int(img.get("width", 512) or 512)
                    p.height      = int(img.get("height", 512) or 512)
                    p.sampler, p.scheduler = map_sampler(img.get("sampler", ""))
                    return p
        except Exception as exc:
            logger.debug(f"[sdimport] Lexica API failed, falling back to scrape: {exc}")

    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    p = GenParams()
    p.source_type = "Lexica"
    p.source_url  = url

    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        try:
            props = json.loads(nd.string).get("props", {}).get("pageProps", {})
            for key in ("prompt", "image", "data"):
                obj = props.get(key)
                if isinstance(obj, dict) and obj.get("prompt"):
                    p.positive = obj["prompt"]
                    p.negative = obj.get("negativePrompt", "")
                    p.cfg      = float(obj.get("guidance", 7.0) or 7.0)
                    p.seed     = int(obj.get("seed", -1) or -1)
                    p.sampler, p.scheduler = map_sampler(obj.get("sampler", ""))
                    if obj.get("width"):  p.width  = int(obj["width"])
                    if obj.get("height"): p.height = int(obj["height"])
                    break
        except Exception as exc:
            logger.debug(f"[sdimport] Lexica __NEXT_DATA__ parse failed: {exc}")

    if not p.positive:
        og = soup.find("meta", property="og:description")
        if og:
            p.positive = og.get("content", "")

    return p


# ---------------------------------------------------------------------------
# Extractor: Direct image URL (download → read PNG metadata)
# ---------------------------------------------------------------------------

def extract_from_image_url(url: str) -> GenParams:
    """Download an image from a URL and read its embedded PNG metadata."""
    requests = _require_requests()

    resp = requests.get(
        url, timeout=20,
        headers={"User-Agent": "GENESIS-sdimport/1.0"},
        stream=True,
    )
    if resp.status_code != 200:
        raise IOError(f"Failed to download image: HTTP {resp.status_code} from {url}")

    content_type = resp.headers.get("content-type", "")
    if "png" not in content_type and not url.lower().endswith(".png"):
        logger.warning(
            f"[sdimport] URL may not be a PNG ({content_type}). "
            "Metadata extraction may return nothing."
        )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
        tmp_path = f.name

    try:
        p = extract_from_png(tmp_path)
        p.source_url  = url
        p.source_type = f"Direct URL ({p.source_type})"
        return p
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Router: dispatch to the right extractor
# ---------------------------------------------------------------------------

def extract(source: str) -> GenParams:
    """
    Extract generation parameters from a URL or local file path.

    Args:
        source: Civitai/PromptHero/Lexica URL, direct image URL,
                or local PNG file path.

    Returns:
        GenParams with extracted metadata.

    Raises:
        ValueError: Unrecognized or unparseable source.
        IOError:    HTTP error or file I/O failure.
        ImportError: Missing optional dependency (requests / beautifulsoup4).
    """
    if os.path.isfile(source):
        logger.debug(f"[sdimport] Local file: {source}")
        return extract_from_png(source)

    parsed = urlparse(source)
    host   = parsed.netloc.lower()

    if "civitai.com" in host:
        return extract_from_civitai(source)
    elif "prompthero.com" in host:
        return extract_from_prompthero(source)
    elif "lexica.art" in host:
        return extract_from_lexica(source)
    elif parsed.scheme in ("http", "https"):
        return extract_from_image_url(source)
    else:
        raise ValueError(
            f"Unrecognized source: {source!r}. "
            "Expected a Civitai/PromptHero/Lexica URL, a direct image URL, "
            "or a local PNG file path."
        )


# ---------------------------------------------------------------------------
# ComfyUI workflow builder
# ---------------------------------------------------------------------------

def build_comfyui_workflow(p: GenParams) -> dict:
    """Build a minimal but complete ComfyUI txt2img workflow dict."""

    if hasattr(p, "_raw_comfyui_workflow"):
        return json.loads(p._raw_comfyui_workflow)

    seed = p.seed if p.seed != -1 else 999999999
    is_xl = any(x in p.model.lower() for x in ["xl", "sdxl", "pony"]) if p.model else False
    width  = p.width  or (1024 if is_xl else 512)
    height = p.height or (1024 if is_xl else 512)

    ckpt = p.model
    if ckpt and "." not in ckpt:
        ckpt += ".safetensors"
    if not ckpt:
        ckpt = "put_your_model_here.safetensors"

    return {
        "1": {
            "inputs":     {"ckpt_name": ckpt},
            "class_type": "CheckpointLoaderSimple",
            "_meta":      {"title": "Load Checkpoint"},
        },
        "2": {
            "inputs":     {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
            "_meta":      {"title": "Empty Latent Image"},
        },
        "3": {
            "inputs":     {"text": p.positive, "clip": ["1", 1]},
            "class_type": "CLIPTextEncode",
            "_meta":      {"title": "Positive Prompt"},
        },
        "4": {
            "inputs":     {"text": p.negative, "clip": ["1", 1]},
            "class_type": "CLIPTextEncode",
            "_meta":      {"title": "Negative Prompt"},
        },
        "5": {
            "inputs": {
                "seed": seed, "steps": p.steps, "cfg": p.cfg,
                "sampler_name": p.sampler, "scheduler": p.scheduler,
                "denoise": 1.0,
                "model":        ["1", 0],
                "positive":     ["3", 0],
                "negative":     ["4", 0],
                "latent_image": ["2", 0],
            },
            "class_type": "KSampler",
            "_meta":      {"title": "KSampler"},
        },
        "6": {
            "inputs":     {"samples": ["5", 0], "vae": ["1", 2]},
            "class_type": "VAEDecode",
            "_meta":      {"title": "VAE Decode"},
        },
        "7": {
            "inputs":     {"filename_prefix": "sdimport", "images": ["6", 0]},
            "class_type": "SaveImage",
            "_meta":      {"title": "Save Image"},
        },
    }
