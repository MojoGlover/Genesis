"""Core vision engine using Ollama vision models."""

import httpx
import base64
import io
from pathlib import Path
from typing import Optional, Union
from PIL import Image

from vision_engine.models import (
    VisionModel,
    VisionResponse,
    ImageAnalysis,
    OCRResult,
    SceneUnderstanding,
    ObjectDetection
)


class VisionEngine:
    """Universal vision AI engine using Ollama."""
    
    def __init__(
        self,
        model: VisionModel = VisionModel.LLAVA_7B,
        ollama_url: str = "http://localhost:11434",
        timeout: float = 120.0
    ):
        """Initialize vision engine.
        
        Args:
            model: Ollama vision model to use
            ollama_url: Ollama API base URL
            timeout: Request timeout in seconds
        """
        self.model = model.value if isinstance(model, VisionModel) else model
        self.ollama_url = ollama_url
        self.client = httpx.Client(timeout=timeout)
    
    def _load_image(self, image: Union[str, Path, Image.Image]) -> Image.Image:
        """Load image from various sources.
        
        Args:
            image: File path, URL, or PIL Image
            
        Returns:
            PIL Image
        """
        if isinstance(image, Image.Image):
            return image
        elif isinstance(image, (str, Path)):
            path = Path(image)
            if path.exists():
                return Image.open(path)
            else:
                # Try as URL
                response = httpx.get(str(image))
                return Image.open(io.BytesIO(response.content))
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")
    
    def _encode_image(self, image: Image.Image, max_size: int = 1024) -> str:
        """Encode PIL image to base64.
        
        Args:
            image: PIL Image
            max_size: Maximum dimension (resizes if larger)
            
        Returns:
            Base64 encoded string
        """
        # Resize if too large
        if max(image.size) > max_size:
            image = image.copy()
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        # Encode to base64
        return base64.b64encode(img_byte_arr).decode('utf-8')
    
    def query(
        self,
        image: Union[str, Path, Image.Image],
        prompt: str,
        stream: bool = False
    ) -> VisionResponse:
        """Query vision model with an image and prompt.
        
        Args:
            image: Image to analyze
            prompt: Question or instruction
            stream: Stream response (not implemented yet)
            
        Returns:
            VisionResponse with model output
        """
        # Load and encode image
        img = self._load_image(image)
        img_b64 = self._encode_image(img)
        
        # Call Ollama API
        response = self.client.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Ollama API error: {response.status_code} - {response.text}")
        
        data = response.json()
        return VisionResponse(**data)
    
    def analyze(
        self,
        image: Union[str, Path, Image.Image],
        detailed: bool = True
    ) -> ImageAnalysis:
        """Comprehensive image analysis.
        
        Args:
            image: Image to analyze
            detailed: Include detailed analysis
            
        Returns:
            Structured ImageAnalysis
        """
        if detailed:
            prompt = """Analyze this image in detail. Provide:
1. Overall description (2-3 sentences)
2. Main objects and elements (list)
3. Any text visible in the image
4. Dominant colors
5. Scene type (indoor/outdoor/etc)
6. Suggested actions or insights

Be thorough but concise."""
        else:
            prompt = "Describe this image briefly in 2-3 sentences."
        
        response = self.query(image, prompt)
        
        # Parse response into structured format
        return self._parse_analysis(response.response)
    
    def _parse_analysis(self, text: str) -> ImageAnalysis:
        """Parse model response into ImageAnalysis.
        
        Args:
            text: Raw model response
            
        Returns:
            Structured ImageAnalysis
        """
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        description = ""
        objects = []
        suggestions = []
        
        for line in lines:
            # First line is usually description
            if not description:
                description = line
            # Lines with numbers/bullets are objects or suggestions
            elif line[0].isdigit() or line.startswith(('-', '•', '*')):
                cleaned = line.lstrip('0123456789.-•* ')
                if any(word in line.lower() for word in ['should', 'could', 'suggest', 'recommend']):
                    suggestions.append(cleaned)
                else:
                    objects.append(cleaned)
        
        return ImageAnalysis(
            description=description or text[:200],
            objects=objects[:10],  # Max 10
            suggestions=suggestions[:5],  # Max 5
            raw_response=text,
            confidence=0.8  # Default confidence
        )
    
    def extract_text(
        self,
        image: Union[str, Path, Image.Image]
    ) -> OCRResult:
        """Extract text from image (OCR).
        
        Args:
            image: Image containing text
            
        Returns:
            OCRResult with extracted text
        """
        prompt = """Extract ALL text visible in this image.
Return ONLY the text, exactly as it appears.
If there's no text, respond with "No text found"."""
        
        response = self.query(image, prompt)
        
        return OCRResult(
            text=response.response,
            confidence=0.75  # Vision models aren't perfect for OCR
        )
    
    def understand_scene(
        self,
        image: Union[str, Path, Image.Image]
    ) -> SceneUnderstanding:
        """High-level scene understanding.
        
        Args:
            image: Image to understand
            
        Returns:
            SceneUnderstanding with context
        """
        prompt = """Analyze this scene and answer:
1. Scene type (indoor, outdoor, street, office, home, etc)
2. What activity or event is happening
3. Key objects present
4. How many people are visible
5. Additional context

Be factual and concise."""
        
        response = self.query(image, prompt)
        
        # Parse response
        lines = response.response.lower().split('\n')
        scene_type = "unknown"
        activity = ""
        people_count = 0
        
        for line in lines:
            if 'indoor' in line or 'outdoor' in line or 'street' in line or 'office' in line:
                scene_type = line.split(':')[-1].strip() if ':' in line else line.strip()
            if 'people' in line or 'person' in line:
                # Try to extract count
                words = line.split()
                for word in words:
                    if word.isdigit():
                        people_count = int(word)
                        break
        
        return SceneUnderstanding(
            scene_type=scene_type,
            activity=activity,
            context=response.response,
            people_count=people_count
        )
    
    def compare_images(
        self,
        image1: Union[str, Path, Image.Image],
        image2: Union[str, Path, Image.Image]
    ) -> str:
        """Compare two images.
        
        Args:
            image1: First image
            image2: Second image
            
        Returns:
            Comparison description
        """
        # Analyze both
        analysis1 = self.analyze(image1, detailed=False)
        analysis2 = self.analyze(image2, detailed=False)
        
        # Create comparison prompt
        prompt = f"""Compare these two scenarios:
Image 1: {analysis1.description}
Image 2: {analysis2.description}

What are the main differences?"""
        
        # For now, return textual comparison
        # In future, could pass both images to model if supported
        return f"Image 1: {analysis1.description}\nImage 2: {analysis2.description}"
    
    def ask_about_image(
        self,
        image: Union[str, Path, Image.Image],
        question: str
    ) -> str:
        """Ask a specific question about an image.
        
        Args:
            image: Image to ask about
            question: Your question
            
        Returns:
            Answer from vision model
        """
        response = self.query(image, question)
        return response.response
    
    def check_model_available(self) -> bool:
        """Check if the vision model is available.
        
        Returns:
            True if model is loaded/available
        """
        try:
            response = self.client.get(f"{self.ollama_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                return any(self.model in m.get("name", "") for m in models)
        except:
            pass
        return False
    
    def pull_model(self) -> bool:
        """Pull/download the vision model if not available.
        
        Returns:
            Success status
        """
        try:
            print(f"📥 Pulling vision model: {self.model}")
            print("⚠️  This may take several minutes (model is ~4GB)...")
            
            response = self.client.post(
                f"{self.ollama_url}/api/pull",
                json={"name": self.model},
                timeout=600.0  # 10 minutes
            )
            
            if response.status_code == 200:
                print(f"✅ Model {self.model} ready!")
                return True
            else:
                print(f"❌ Pull failed: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Error pulling model: {e}")
            return False
