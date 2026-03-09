"""ADB bridge for wireless screenshot capture and full device control."""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from PIL import Image
import io


class ADBBridge:
    """Manages ADB connection and screenshot capture with full device access."""
    
    def __init__(self, device_ip: Optional[str] = None, port: int = 5555):
        """Initialize ADB bridge.
        
        Args:
            device_ip: Tablet IP address (None for USB)
            port: ADB port (default 5555)
        """
        self.device_ip = device_ip
        self.port = port
        self.connected = False
        
    def connect(self) -> bool:
        """Connect to tablet via wireless ADB or USB."""
        try:
            if self.device_ip:
                # Wireless ADB
                result = subprocess.run(
                    ["adb", "connect", f"{self.device_ip}:{self.port}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                self.connected = "connected" in result.stdout.lower()
            else:
                # USB ADB - check if device connected
                result = subprocess.run(
                    ["adb", "devices"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                self.connected = len(result.stdout.strip().split('\n')) > 1
                
            return self.connected
        except Exception as e:
            print(f"❌ ADB connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from tablet."""
        if self.device_ip:
            subprocess.run(
                ["adb", "disconnect", f"{self.device_ip}:{self.port}"],
                capture_output=True,
                timeout=5
            )
        self.connected = False
    
    def capture_screenshot(self) -> Optional[Image.Image]:
        """Capture screenshot from tablet.
        
        Returns:
            PIL Image or None if capture failed
        """
        if not self.connected:
            print("❌ Not connected to tablet")
            return None
        
        try:
            # Capture screenshot directly to stdout
            result = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Load image from bytes
                image = Image.open(io.BytesIO(result.stdout))
                return image
            else:
                print(f"❌ Screenshot capture failed: {result.stderr.decode()}")
                return None
                
        except Exception as e:
            print(f"❌ Screenshot error: {e}")
            return None
    
    def get_screen_size(self) -> Optional[tuple[int, int]]:
        """Get tablet screen resolution.
        
        Returns:
            (width, height) or None
        """
        try:
            result = subprocess.run(
                ["adb", "shell", "wm", "size"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parse output like "Physical size: 1920x1200"
            if result.returncode == 0:
                size_str = result.stdout.strip().split(": ")[-1]
                width, height = map(int, size_str.split("x"))
                return (width, height)
        except Exception as e:
            print(f"❌ Failed to get screen size: {e}")
        return None
    
    def tap(self, x: int, y: int) -> bool:
        """Simulate tap at coordinates.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Success status
        """
        try:
            result = subprocess.run(
                ["adb", "shell", "input", "tap", str(x), str(y)],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Tap failed: {e}")
            return False
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """Simulate swipe gesture.
        
        Args:
            x1, y1: Start coordinates
            x2, y2: End coordinates
            duration_ms: Swipe duration in milliseconds
            
        Returns:
            Success status
        """
        try:
            result = subprocess.run(
                ["adb", "shell", "input", "swipe", 
                 str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Swipe failed: {e}")
            return False
    
    def type_text(self, text: str) -> bool:
        """Type text on tablet.
        
        Args:
            text: Text to type
            
        Returns:
            Success status
        """
        try:
            # Escape special characters
            escaped = text.replace(" ", "%s").replace("'", "\\'")
            result = subprocess.run(
                ["adb", "shell", "input", "text", escaped],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Type text failed: {e}")
            return False
    
    def launch_app(self, package_name: str) -> bool:
        """Launch app by package name.
        
        Args:
            package_name: Android package name (e.g., "com.android.chrome")
            
        Returns:
            Success status
        """
        try:
            result = subprocess.run(
                ["adb", "shell", "monkey", "-p", package_name, "-c", 
                 "android.intent.category.LAUNCHER", "1"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Launch app failed: {e}")
            return False
    
    def shell_command(self, command: str) -> Optional[str]:
        """Execute arbitrary shell command on tablet.
        
        Args:
            command: Shell command to execute
            
        Returns:
            Command output or None if failed
        """
        try:
            result = subprocess.run(
                ["adb", "shell", command],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"❌ Shell command failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Shell command error: {e}")
            return None
    
    def install_apk(self, apk_path: str) -> bool:
        """Install APK file on tablet.
        
        Args:
            apk_path: Path to APK file
            
        Returns:
            Success status
        """
        try:
            result = subprocess.run(
                ["adb", "install", "-r", apk_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            return "Success" in result.stdout
        except Exception as e:
            print(f"❌ APK install failed: {e}")
            return False
