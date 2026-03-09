"""
Vision Tool
Analyze images using LLaVA model
"""
import base64
import httpx
from typing import Dict, Any


async def analyze_image(image_path: str, prompt: str = "Describe this image") -> Dict[str, Any]:
    """
    Analyze an image using LLaVA vision model
    
    Args:
        image_path: Path to image file
        prompt: Question/instruction about the image
        
    Returns:
        Analysis results
    """
    # Read and encode image
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()
    
    # Call Ollama with vision model
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llava:13b",
                "prompt": prompt,
                "images": [image_data],
                "stream": False
            }
        )
        return response.json()
