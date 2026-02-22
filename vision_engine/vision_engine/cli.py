"""CLI for testing vision engine."""

import sys
from pathlib import Path
from vision_engine import VisionEngine, VisionModel


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Vision Engine CLI")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("--model", default="llava:7b", help="Vision model to use")
    parser.add_argument("--analyze", action="store_true", help="Full analysis")
    parser.add_argument("--ocr", action="store_true", help="Extract text")
    parser.add_argument("--scene", action="store_true", help="Scene understanding")
    parser.add_argument("--ask", type=str, help="Ask a question about the image")
    parser.add_argument("--pull", action="store_true", help="Pull model if needed")
    
    args = parser.parse_args()
    
    # Check if image exists
    if not Path(args.image).exists():
        print(f"❌ Image not found: {args.image}")
        sys.exit(1)
    
    # Create engine
    engine = VisionEngine(model=args.model)
    
    # Check/pull model
    if not engine.check_model_available():
        if args.pull:
            if not engine.pull_model():
                print("❌ Failed to pull model")
                sys.exit(1)
        else:
            print(f"❌ Model {args.model} not available")
            print("Run with --pull to download it")
            sys.exit(1)
    
    print(f"🤖 Using model: {args.model}\n")
    
    # Execute requested operation
    if args.analyze:
        print("📊 Analyzing image...\n")
        result = engine.analyze(args.image)
        print(f"Description: {result.description}\n")
        if result.objects:
            print("Objects detected:")
            for obj in result.objects:
                print(f"  • {obj}")
        if result.suggestions:
            print("\nSuggestions:")
            for sug in result.suggestions:
                print(f"  💡 {sug}")
    
    elif args.ocr:
        print("📝 Extracting text...\n")
        result = engine.extract_text(args.image)
        print(f"Text found:\n{result.text}")
        print(f"\nConfidence: {result.confidence:.0%}")
    
    elif args.scene:
        print("🎬 Understanding scene...\n")
        result = engine.understand_scene(args.image)
        print(f"Scene type: {result.scene_type}")
        print(f"People count: {result.people_count}")
        print(f"\nContext:\n{result.context}")
    
    elif args.ask:
        print(f"❓ Question: {args.ask}\n")
        answer = engine.ask_about_image(args.image, args.ask)
        print(f"💬 Answer: {answer}")
    
    else:
        # Default: quick description
        print("📸 Quick description...\n")
        result = engine.analyze(args.image, detailed=False)
        print(result.description)


if __name__ == "__main__":
    main()
