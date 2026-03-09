"""Vision-based screen understanding using Ollama vision models."""

import httpx
from typing import Optional
from PIL import Image
import base64
import io
from pydantic import BaseModel, Field


class ScreenAnalysis(BaseModel):
    """Results from screen analysis."""
    description: str = Field(description="What's on the screen")
    elements: list[dict] = Field(default_factory=list, description="UI elements detected")
    suggestions: list[str] = Field(default_factory=list, description="What the AI suggests")
    context: str = Field(default="", description="Current app/activity context")


class VisionAssistant:
    """Analyzes tablet screenshots using Ollama vision models."""
    
    def __init__(
        self,
        model: str = "llava:7b",
        ollama_url: str = "http://localhost:11434"
    ):
        """Initialize vision assistant.
        
        Args:
            model: Ollama vision model name (llava, bakllava)
            ollama_url: Ollama API URL
        """
        self.model = model
        self.ollama_url = ollama_url
        self.client = httpx.Client(timeout=60.0)
        
    def _encode_image(self, image: Image.Image) -> str:
        """Encode PIL image to base64.
        
        Args:
            image: PIL Image
            
        Returns:
            Base64 encoded string
        """
        # Resize if too large (vision models work better with smaller images)
        max_size = 1024
        if max(image.size) > max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        # Encode to base64
        return base64.b64encode(img_byte_arr).decode('utf-8')
    
    def analyze_screen(
        self,
        screenshot: Image.Image,
        question: Optional[str] = None
    ) -> ScreenAnalysis:
        """Analyze screenshot with vision model.
        
        Args:
            screenshot: PIL Image of screen
            question: Optional specific question about the screen
            
        Returns:
            ScreenAnalysis with AI insights
        """
        # Default prompt if no question
        if not question:
            prompt = """Analyze this Android tablet screen. Describe:
1. What app or screen is shown
2. Main UI elements (buttons, text fields, images)
3. What the user might want to do next
4. Any helpful suggestions

Be concise and practical."""
        else:
            prompt = question
        
        # Encode image
        image_b64 = self._encode_image(screenshot)
        
        try:
            # Call Ollama vision API
            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                
                # Parse response into structured format
                return self._parse_analysis(response_text)
            else:
                print(f"❌ Vision API error: {response.status_code}")
                return ScreenAnalysis(
                    description="Failed to analyze screen",
                    suggestions=["Check Ollama connection"]
                )
                
        except Exception as e:
            print(f"❌ Vision analysis error: {e}")
            return ScreenAnalysis(
                description=f"Error: {e}",
                suggestions=["Verify Ollama is running"]
            )
    
    def _parse_analysis(self, response_text: str) -> ScreenAnalysis:
        """Parse vision model response into structured format.
        
        Args:
            response_text: Raw model response
            
        Returns:
            Structured ScreenAnalysis
        """
        # Simple parsing - can be enhanced with structured output
        lines = response_text.strip().split('\n')
        
        description = ""
        suggestions = []
        
        for line in lines:
            line = line.strip()
            if line:
                # First non-empty line is description
                if not description:
                    description = line
                # Lines starting with numbers or bullets are suggestions
                elif line[0].isdigit() or line.startswith('-') or line.startswith('•'):
                    suggestions.append(line.lstrip('0123456789.-• '))
        
        return ScreenAnalysis(
            description=description or response_text[:200],
            suggestions=suggestions or [response_text] if response_text else []
        )
    
    def ask_about_screen(
        self,
        screenshot: Image.Image,
        question: str
    ) -> str:
        """Ask a specific question about the screen.
        
        Args:
            screenshot: PIL Image of screen
            question: Question to ask
            
        Returns:
            AI's answer
        """
        image_b64 = self._encode_image(screenshot)
        
        try:
            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": question,
                    "images": [image_b64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                return response.json().get("response", "No response")
            else:
                return f"Error: {response.status_code}"
                
        except Exception as e:
            return f"Error: {e}"
    
    def detect_ui_elements(self, screenshot: Image.Image) -> list[dict]:
        """Detect UI elements on screen (buttons, text fields, etc).
        
        Args:
            screenshot: PIL Image of screen
            
        Returns:
            List of detected elements with positions
        """
        prompt = """List all interactive UI elements on this screen.
For each element, provide:
- Type (button, text field, image, etc)
- Approximate position (top-left, center, bottom-right, etc)
- Purpose or label

Format as a simple numbered list."""
        
        image_b64 = self._encode_image(screenshot)
        
        try:
            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                text = response.json().get("response", "")
                # Parse into list of elements
                elements = []
                for line in text.split('\n'):
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-')):
                        elements.append({"description": line.lstrip('0123456789.-• ')})
                return elements
            else:
                return []
                
        except Exception as e:
            print(f"❌ Element detection error: {e}")
            return []
