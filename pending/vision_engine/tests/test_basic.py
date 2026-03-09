"""Basic tests for vision_engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import():
    """Test vision_engine imports correctly."""
    from vision_engine import VisionEngine, VisionModel, ImageAnalysis
    assert VisionEngine is not None
    assert VisionModel is not None


def test_model_enum():
    """Test VisionModel enum values."""
    from vision_engine.models import VisionModel
    assert VisionModel.LLAVA_7B.value == "llava:7b"
    assert VisionModel.LLAVA_PHI3.value == "llava-phi3"


def test_image_analysis_model():
    """Test ImageAnalysis Pydantic model."""
    from vision_engine.models import ImageAnalysis
    a = ImageAnalysis(description="A test image", objects=["cat", "dog"])
    assert a.description == "A test image"
    assert len(a.objects) == 2
    assert a.confidence == 0.0  # default


def test_engine_init():
    """Test VisionEngine initialization."""
    from vision_engine import VisionEngine
    engine = VisionEngine(model="llava:7b")
    assert engine.model == "llava:7b"
    assert engine.ollama_url == "http://localhost:11434"


def test_encode_image():
    """Test image encoding to base64."""
    from vision_engine import VisionEngine
    from PIL import Image
    import io, base64
    
    engine = VisionEngine()
    # Create a tiny test image
    img = Image.new('RGB', (100, 100), color='red')
    b64 = engine._encode_image(img)
    
    assert isinstance(b64, str)
    # Verify it's valid base64
    decoded = base64.b64decode(b64)
    img_back = Image.open(io.BytesIO(decoded))
    assert img_back.size[0] <= 100
