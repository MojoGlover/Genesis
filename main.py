"""
GENESIS - Autonomous AI Agent
Main entry point
"""

import logging
import sys
from core.agent import AutonomousAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    print("=" * 60)
    print("GENESIS - Autonomous AI Agent")
    print("=" * 60)
    print()
    
    # Get task from command line or prompt
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = input("Enter task: ")
    
    if not task:
        print("No task provided. Exiting.")
        return
    
    print(f"\nTask: {task}\n")
    
    # Initialize agent
    agent = AutonomousAgent(max_iterations=20)
    
    # Run autonomous loop
    print("Starting autonomous execution...\n")
    result = agent.run(task)
    
    # Display results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Status: {result['status']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Success: {result['success']}")
    
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    print(f"\nSteps executed: {len(result['execution_history'])}")
    
    for i, entry in enumerate(result['execution_history'], 1):
        step = entry['step']
        step_result = entry['result']
        print(f"\n{i}. {step.get('description', 'Step')}")
        print(f"   Action: {step.get('action')}")
        print(f"   Success: {step_result.get('success')}")
        if step_result.get('output'):
            output = str(step_result['output'])[:200]
            print(f"   Output: {output}...")


if __name__ == "__main__":
    main()
