"""Main tablet companion orchestrator."""

import asyncio
import time
from pathlib import Path
from typing import Optional
from PIL import Image

from tablet_assistant.adb_bridge import ADBBridge
from tablet_assistant.vision_assistant import VisionAssistant
from tablet_assistant.overlay_generator import OverlayGenerator


class TabletCompanion:
    """AI companion for Android tablets with overlay assistance."""
    
    def __init__(
        self,
        tablet_ip: Optional[str] = None,
        vision_model: str = "llava:7b",
        ollama_url: str = "http://localhost:11434"
    ):
        """Initialize tablet companion.
        
        Args:
            tablet_ip: Tablet IP for wireless ADB (None for USB)
            vision_model: Ollama vision model to use
            ollama_url: Ollama API URL
        """
        self.adb = ADBBridge(device_ip=tablet_ip)
        self.vision = VisionAssistant(model=vision_model, ollama_url=ollama_url)
        self.overlay = OverlayGenerator()
        self.running = False
        
        # State
        self.last_screenshot: Optional[Image.Image] = None
        self.last_analysis = None
        
    def connect(self) -> bool:
        """Connect to tablet.
        
        Returns:
            Success status
        """
        print("🔌 Connecting to tablet...")
        if self.adb.connect():
            size = self.adb.get_screen_size()
            print(f"✅ Connected! Screen size: {size}")
            return True
        else:
            print("❌ Connection failed")
            return False
    
    def capture_and_analyze(self) -> Optional[Image.Image]:
        """Capture screenshot and analyze it.
        
        Returns:
            Screenshot with overlay or None
        """
        print("📸 Capturing screenshot...")
        screenshot = self.adb.capture_screenshot()
        
        if not screenshot:
            print("❌ Screenshot capture failed")
            return None
        
        self.last_screenshot = screenshot
        
        print("🤖 Analyzing with AI...")
        analysis = self.vision.analyze_screen(screenshot)
        self.last_analysis = analysis
        
        print(f"\n📱 {analysis.description}")
        if analysis.suggestions:
            print("\n💡 Suggestions:")
            for i, suggestion in enumerate(analysis.suggestions, 1):
                print(f"  {i}. {suggestion}")
        
        # Create overlay
        overlay_image = self.overlay.create_help_overlay(
            screenshot,
            title="🤖 AI Assistant",
            description=analysis.description,
            suggestions=analysis.suggestions
        )
        
        return overlay_image
    
    def ask_question(self, question: str) -> str:
        """Ask AI a question about current screen.
        
        Args:
            question: Question to ask
            
        Returns:
            AI's answer
        """
        if not self.last_screenshot:
            return "No screenshot available. Capture one first."
        
        print(f"\n❓ Question: {question}")
        answer = self.vision.ask_about_screen(self.last_screenshot, question)
        print(f"💬 Answer: {answer}")
        return answer
    
    def monitor_mode(self, interval: float = 5.0):
        """Continuous monitoring mode with periodic analysis.
        
        Args:
            interval: Seconds between captures
        """
        print(f"\n👁️  Starting monitor mode (capturing every {interval}s)")
        print("Press Ctrl+C to stop\n")
        
        self.running = True
        
        try:
            while self.running:
                overlay_img = self.capture_and_analyze()
                
                if overlay_img:
                    # Save to temp file for viewing
                    output_path = Path("/tmp/tablet_overlay.png")
                    overlay_img.save(output_path)
                    print(f"💾 Saved overlay to {output_path}")
                
                print(f"\n⏸️  Waiting {interval}s...\n")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Monitor mode stopped")
            self.running = False
    
    def interactive_mode(self):
        """Interactive CLI mode."""
        print("\n🎮 Interactive Mode")
        print("Commands:")
        print("  capture - Capture and analyze screen")
        print("  ask <question> - Ask about the screen")
        print("  tap <x> <y> - Tap at coordinates")
        print("  type <text> - Type text")
        print("  app <package> - Launch app")
        print("  shell <cmd> - Run shell command")
        print("  quit - Exit")
        print()
        
        while True:
            try:
                cmd = input("📱 > ").strip()
                
                if not cmd:
                    continue
                
                if cmd == "quit":
                    break
                
                elif cmd == "capture":
                    self.capture_and_analyze()
                
                elif cmd.startswith("ask "):
                    question = cmd[4:]
                    self.ask_question(question)
                
                elif cmd.startswith("tap "):
                    _, x, y = cmd.split()
                    if self.adb.tap(int(x), int(y)):
                        print("✅ Tapped")
                    else:
                        print("❌ Tap failed")
                
                elif cmd.startswith("type "):
                    text = cmd[5:]
                    if self.adb.type_text(text):
                        print("✅ Typed")
                    else:
                        print("❌ Type failed")
                
                elif cmd.startswith("app "):
                    package = cmd[4:]
                    if self.adb.launch_app(package):
                        print(f"✅ Launched {package}")
                    else:
                        print("❌ Launch failed")
                
                elif cmd.startswith("shell "):
                    shell_cmd = cmd[6:]
                    result = self.adb.shell_command(shell_cmd)
                    if result:
                        print(result)
                    else:
                        print("❌ Command failed")
                
                else:
                    print("❌ Unknown command")
                    
            except KeyboardInterrupt:
                print("\n👋 Exiting")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def disconnect(self):
        """Disconnect from tablet."""
        print("👋 Disconnecting...")
        self.adb.disconnect()


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="AI Tablet Companion")
    parser.add_argument("--tablet-ip", help="Tablet IP address for wireless ADB")
    parser.add_argument("--model", default="llava:7b", help="Ollama vision model")
    parser.add_argument("--monitor", action="store_true", help="Start in monitor mode")
    parser.add_argument("--interval", type=float, default=5.0, help="Monitor interval (seconds)")
    
    args = parser.parse_args()
    
    # Create companion
    companion = TabletCompanion(
        tablet_ip=args.tablet_ip,
        vision_model=args.model
    )
    
    # Connect
    if not companion.connect():
        print("❌ Failed to connect to tablet")
        print("\nSetup instructions:")
        print("1. Enable Developer Options: Settings → About → Tap 'Build number' 7 times")
        print("2. Enable USB Debugging: Settings → Developer Options → USB debugging")
        print("3. For wireless: Settings → Developer Options → Wireless debugging")
        print("4. Connect USB or use --tablet-ip <IP_ADDRESS>")
        return
    
    try:
        if args.monitor:
            companion.monitor_mode(interval=args.interval)
        else:
            companion.interactive_mode()
    finally:
        companion.disconnect()


if __name__ == "__main__":
    main()
