"""Test script for Rasa module."""
import sys
from pathlib import Path

# Add module to path
sys.path.insert(0, str(Path(__file__).parent))

from rasa_module import SimplifiedRasaAgent


def main():
    print("🤖 Rasa Module Test")
    print("=" * 50)
    print("Testing Ollama-based conversational agent")
    print("Type 'quit' to exit\n")
    
    agent = SimplifiedRasaAgent(model="phi3:mini")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'bye']:
                print("Agent: Goodbye!")
                break
            
            response = agent.process_message(user_input)
            print(f"Agent: {response}\n")
        
        except KeyboardInterrupt:
            print("\n\nAgent: Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
