# Vision Engine

Universal vision AI engine using Ollama vision models.

## Features

- 🔍 **Image Analysis** - Comprehensive understanding of images
- 📝 **OCR** - Extract text from images
- 🎬 **Scene Understanding** - Identify scene type, objects, context
- ❓ **Question Answering** - Ask questions about images
- 🖼️ **Multi-format Support** - PIL Images, file paths, URLs

## Models Supported

- `llava:7b` - Recommended (4GB, fast)
- `llava:13b` - Better quality (7GB, slower)
- `llava:34b` - Highest quality (19GB, slowest)
- `bakllava` - Alternative architecture
- `llava-llama3` - Latest Llama 3 base
- `llava-phi3` - Phi-3 base (smaller, faster)

## Installation

```bash
cd ~/ai/GENESIS/vision_engine
pip install -e .

# Pull vision model (required first time)
ollama pull llava:7b
```

## Usage

### Python API

```python
from vision_engine import VisionEngine

# Initialize
engine = VisionEngine(model="llava:7b")

# Analyze image
analysis = engine.analyze("photo.jpg")
print(analysis.description)
print(analysis.objects)
print(analysis.suggestions)

# Extract text (OCR)
text = engine.extract_text("screenshot.png")
print(text.text)

# Scene understanding
scene = engine.understand_scene("street.jpg")
print(f"Scene: {scene.scene_type}")
print(f"People: {scene.people_count}")

# Ask questions
answer = engine.ask_about_image(
    "tablet.png",
    "What app is showing on this screen?"
)
print(answer)
```

### CLI

```bash
# Quick description
python -m vision_engine.cli photo.jpg

# Full analysis
python -m vision_engine.cli photo.jpg --analyze

# Extract text
python -m vision_engine.cli screenshot.png --ocr

# Scene understanding
python -m vision_engine.cli street.jpg --scene

# Ask question
python -m vision_engine.cli tablet.png --ask "What buttons are visible?"

# Pull model if not installed
python -m vision_engine.cli photo.jpg --pull --analyze
```

## Integration Examples

### Engineer0 Integration
```python
from vision_engine import VisionEngine

engine = VisionEngine()
analysis = engine.analyze(screenshot_path)
# Use analysis.description in chat
```

### Tablet Assistant Integration
```python
from vision_engine import VisionEngine

engine = VisionEngine()
screenshot = adb.capture_screenshot()
answer = engine.ask_about_image(
    screenshot,
    "What should I tap to open settings?"
)
```

## API Reference

### `VisionEngine`

**Methods:**
- `analyze(image, detailed=True)` → `ImageAnalysis`
- `extract_text(image)` → `OCRResult`
- `understand_scene(image)` → `SceneUnderstanding`
- `ask_about_image(image, question)` → `str`
- `query(image, prompt)` → `VisionResponse`
- `check_model_available()` → `bool`
- `pull_model()` → `bool`

**Models:**
- `ImageAnalysis` - Structured analysis with description, objects, suggestions
- `OCRResult` - Extracted text with confidence
- `SceneUnderstanding` - Scene type, activity, people count
- `VisionResponse` - Raw model output

## Performance

- **llava:7b** - ~2-5s per image (Recommended)
- **llava:13b** - ~5-10s per image (Better quality)
- **llava:34b** - ~15-30s per image (Best quality)

Requires ~4-19GB RAM depending on model.

## Requirements

- Ollama running locally
- Python 3.11+
- PIL, httpx, numpy

## License

MIT
