"""Generate visual overlays with AI annotations."""

from PIL import Image, ImageDraw, ImageFont
import io
from typing import Optional


class OverlayGenerator:
    """Creates visual overlays on screenshots."""
    
    def __init__(self, font_size: int = 24):
        """Initialize overlay generator.
        
        Args:
            font_size: Default font size for text
        """
        self.font_size = font_size
        try:
            # Try to load a nice font
            self.font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except:
            # Fallback to default
            self.font = ImageFont.load_default()
    
    def add_text_overlay(
        self,
        image: Image.Image,
        text: str,
        position: tuple[int, int] = (20, 20),
        bg_color: tuple[int, int, int, int] = (0, 0, 0, 180),
        text_color: tuple[int, int, int] = (255, 255, 255)
    ) -> Image.Image:
        """Add text overlay to image.
        
        Args:
            image: Source image
            text: Text to overlay
            position: (x, y) position for text
            bg_color: Background color (RGBA)
            text_color: Text color (RGB)
            
        Returns:
            Image with overlay
        """
        # Create copy to avoid modifying original
        img_copy = image.copy()
        
        # Create drawing context
        draw = ImageDraw.Draw(img_copy, 'RGBA')
        
        # Calculate text size
        bbox = draw.textbbox((0, 0), text, font=self.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Draw background box
        padding = 10
        box_coords = [
            position[0] - padding,
            position[1] - padding,
            position[0] + text_width + padding,
            position[1] + text_height + padding
        ]
        draw.rectangle(box_coords, fill=bg_color)
        
        # Draw text
        draw.text(position, text, fill=text_color, font=self.font)
        
        return img_copy
    
    def add_suggestion_overlay(
        self,
        image: Image.Image,
        suggestions: list[str],
        position: str = "bottom"
    ) -> Image.Image:
        """Add suggestion list overlay.
        
        Args:
            image: Source image
            suggestions: List of suggestion strings
            position: "top" or "bottom"
            
        Returns:
            Image with suggestions overlay
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy, 'RGBA')
        
        # Combine suggestions
        suggestion_text = "\n".join([f"💡 {s}" for s in suggestions[:3]])  # Max 3
        
        # Calculate position
        if position == "bottom":
            y_pos = img_copy.height - 150
        else:
            y_pos = 20
        
        # Add text with semi-transparent background
        return self.add_text_overlay(
            img_copy,
            suggestion_text,
            position=(20, y_pos),
            bg_color=(30, 30, 30, 200),
            text_color=(100, 255, 100)
        )
    
    def highlight_area(
        self,
        image: Image.Image,
        coords: tuple[int, int, int, int],
        color: tuple[int, int, int] = (255, 0, 0),
        width: int = 3
    ) -> Image.Image:
        """Highlight a rectangular area.
        
        Args:
            image: Source image
            coords: (x1, y1, x2, y2) rectangle coordinates
            color: Border color (RGB)
            width: Border width
            
        Returns:
            Image with highlighted area
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        
        # Draw rectangle
        draw.rectangle(coords, outline=color, width=width)
        
        return img_copy
    
    def add_arrow(
        self,
        image: Image.Image,
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int] = (255, 100, 0),
        width: int = 4
    ) -> Image.Image:
        """Draw an arrow pointing to a location.
        
        Args:
            image: Source image
            start: (x, y) arrow start
            end: (x, y) arrow end
            color: Arrow color (RGB)
            width: Arrow line width
            
        Returns:
            Image with arrow
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        
        # Draw line
        draw.line([start, end], fill=color, width=width)
        
        # Draw arrowhead (simple triangle)
        # TODO: Calculate proper arrow head geometry
        arrow_size = 20
        draw.ellipse(
            [end[0]-arrow_size//2, end[1]-arrow_size//2,
             end[0]+arrow_size//2, end[1]+arrow_size//2],
            fill=color
        )
        
        return img_copy
    
    def create_help_overlay(
        self,
        image: Image.Image,
        title: str,
        description: str,
        suggestions: list[str]
    ) -> Image.Image:
        """Create comprehensive help overlay.
        
        Args:
            image: Source image
            title: Help title
            description: Description text
            suggestions: List of suggestions
            
        Returns:
            Image with full help overlay
        """
        img_copy = image.copy()
        
        # Add title at top
        img_copy = self.add_text_overlay(
            img_copy,
            title,
            position=(20, 20),
            bg_color=(0, 100, 200, 220),
            text_color=(255, 255, 255)
        )
        
        # Add description below title
        img_copy = self.add_text_overlay(
            img_copy,
            description[:100],  # Limit length
            position=(20, 80),
            bg_color=(50, 50, 50, 200),
            text_color=(240, 240, 240)
        )
        
        # Add suggestions at bottom
        if suggestions:
            img_copy = self.add_suggestion_overlay(
                img_copy,
                suggestions,
                position="bottom"
            )
        
        return img_copy
