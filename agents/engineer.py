"""
Engineer Agent - Autonomous coding agent with test-fix loop

Capabilities:
- Write code to workspace
- Execute and test automatically
- Detect errors from output
- Fix problems iteratively
- Verify solutions work
"""

import logging
import re
from typing import Dict, Any, List, Optional
from core.agent import AutonomousAgent, AgentContext, AgentState
from core.workspace import workspace

logger = logging.getLogger(__name__)


class EngineerAgent(AutonomousAgent):
    """
    Specialized agent for autonomous coding tasks
    Extends base agent with code-specific capabilities
    """
    
    def __init__(self, model_name: str = "gpt-4", max_iterations: int = 50):
        super().__init__(model_name, max_iterations)
        self.test_fix_iterations = 0
        self.max_test_fix_iterations = 10
    
    def _execution_step(self, context: AgentContext) -> AgentContext:
        """Enhanced execution with automatic error detection and fixing"""
        logger.info("Engineer execution step...")
        
        next_step = self._get_next_step(context.plan)
        
        if not next_step:
            context.state = AgentState.REFLECTING
            return context
        
        action = next_step.get("action")
        logger.info(f"Executing: {action}")
        
        # Execute the step
        result = self.executor.execute(
            action=action,
            parameters=next_step.get("parameters", {}),
            context=context.execution_history
        )
        
        # Record result
        context.execution_history.append({
            "step": next_step,
            "result": result,
            "iteration": context.iterations
        })
        
        # Check if this was a code execution step
        if action == "workspace_execute" and not result.get("success"):
            # Code failed - enter test-fix loop
            logger.warning("Code execution failed, entering test-fix loop")
            context = self._test_fix_loop(context, next_step, result)
        else:
            # Normal step completion
            next_step["status"] = "complete" if result.get("success") else "failed"
            next_step["result"] = result
            
            if not result.get("success"):
                context.state = AgentState.REFLECTING
        
        return context
    
    def _test_fix_loop(
        self,
        context: AgentContext,
        failed_step: Dict[str, Any],
        error_result: Dict[str, Any]
    ) -> AgentContext:
        """
        Automatic test-fix loop for code errors
        
        1. Detect error type
        2. Generate fix
        3. Apply fix
        4. Test again
        5. Repeat until working or max iterations
        """
        self.test_fix_iterations = 0
        
        while self.test_fix_iterations < self.max_test_fix_iterations:
            self.test_fix_iterations += 1
            logger.info(f"Test-fix iteration {self.test_fix_iterations}/{self.max_test_fix_iterations}")
            
            # Analyze error
            error_analysis = self._analyze_error(error_result)
            logger.info(f"Error type: {error_analysis['type']}")
            
            # Generate fix
            fix = self._generate_fix(
                step=failed_step,
                error=error_analysis,
                context=context
            )
            
            if not fix:
                logger.error("Could not generate fix")
                failed_step["status"] = "failed"
                failed_step["result"] = error_result
                break
            
            # Apply fix
            logger.info(f"Applying fix: {fix['description']}")
            fix_result = self._apply_fix(fix)
            
            if not fix_result.get("success"):
                logger.warning("Fix application failed")
                continue
            
            # Test again
            logger.info("Testing fixed code...")
            test_result = self.executor.execute(
                action=failed_step.get("action"),
                parameters=failed_step.get("parameters", {}),
                context=context.execution_history
            )
            
            # Record fix attempt
            context.execution_history.append({
                "type": "fix_attempt",
                "iteration": self.test_fix_iterations,
                "fix": fix,
                "result": test_result
            })
            
            if test_result.get("success"):
                logger.info("✅ Fix successful!")
                failed_step["status"] = "complete"
                failed_step["result"] = test_result
                failed_step["fixes_applied"] = self.test_fix_iterations
                return context
            else:
                logger.warning("Fix didn't resolve issue, trying again...")
                error_result = test_result
        
        # Max iterations reached
        logger.error(f"Could not fix error after {self.test_fix_iterations} attempts")
        failed_step["status"] = "failed"
        failed_step["result"] = error_result
        context.state = AgentState.REFLECTING
        
        return context
    
    def _analyze_error(self, error_result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze error to determine type and cause"""
        
        error_text = error_result.get("error", "") + error_result.get("output", "")
        
        # Common error patterns
        patterns = {
            "syntax": r"SyntaxError|IndentationError|invalid syntax",
            "import": r"ModuleNotFoundError|ImportError|No module named",
            "name": r"NameError|name .* is not defined",
            "type": r"TypeError",
            "attribute": r"AttributeError",
            "value": r"ValueError",
            "runtime": r"RuntimeError|Exception",
        }
        
        for error_type, pattern in patterns.items():
            if re.search(pattern, error_text, re.IGNORECASE):
                return {
                    "type": error_type,
                    "message": error_text,
                    "raw": error_result
                }
        
        return {
            "type": "unknown",
            "message": error_text,
            "raw": error_result
        }
    
    def _generate_fix(
        self,
        step: Dict[str, Any],
        error: Dict[str, Any],
        context: AgentContext
    ) -> Optional[Dict[str, Any]]:
        """Generate fix based on error type"""
        
        error_type = error["type"]
        error_msg = error["message"]
        
        # TODO: Use LLM to generate intelligent fixes
        # For now, handle common cases
        
        if error_type == "import":
            # Extract missing module - fixed regex
            match = re.search(r"No module named ([a-zA-Z0-9_]+)", error_msg)
            if match:
                module = match.group(1)
                return {
                    "type": "install_package",
                    "description": f"Install missing package: {module}",
                    "action": "workspace_install",
                    "parameters": {"package": module}
                }
        
        elif error_type == "syntax":
            # For syntax errors, would need to read file and fix it
            # This requires LLM to rewrite code
            return {
                "type": "code_rewrite",
                "description": "Fix syntax error in code",
                "needs_llm": True,
                "error": error_msg
            }
        
        elif error_type == "name":
            # Undefined variable - might need to add import or define it
            return {
                "type": "code_fix",
                "description": "Fix undefined variable",
                "needs_llm": True,
                "error": error_msg
            }
        
        else:
            # Generic fix - needs LLM analysis
            return {
                "type": "generic_fix",
                "description": f"Fix {error_type} error",
                "needs_llm": True,
                "error": error_msg
            }
    
    def _apply_fix(self, fix: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the generated fix"""
        
        fix_type = fix["type"]
        
        if fix_type == "install_package":
            # Install missing package
            result = self.executor.execute(
                action=fix["action"],
                parameters=fix["parameters"]
            )
            return result
        
        elif fix.get("needs_llm"):
            # TODO: Use LLM to generate code fix
            # For now, return failure to trigger reflection
            logger.info("Fix requires LLM - would generate code fix here")
            return {"success": False, "error": "LLM fix not implemented yet"}
        
        else:
            return {"success": False, "error": f"Unknown fix type: {fix_type}"}
    
    def run_coding_task(self, task: str, filepath: str = "/workspace/main.py") -> Dict[str, Any]:
        """
        High-level method for coding tasks with automatic testing
        
        Args:
            task: Description of what to build
            filepath: Where to save the code
            
        Returns:
            Result dict with code, tests, and verification
        """
        logger.info(f"Starting coding task: {task}")
        
        # Run the autonomous loop
        result = self.run(task)
        
        # Add coding-specific metadata
        if result["success"]:
            # Get the created files
            files_result = workspace.list_directory("/workspace")
            result["files_created"] = files_result.get("listing", "")
            
            # Get the final code
            if workspace.execute(f"test -f {filepath}").get("success"):
                code_result = workspace.read_file(filepath)
                result["final_code"] = code_result.get("content", "")
        
        return result


def main():
    """Test the engineer agent"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    engineer = EngineerAgent(max_iterations=30)
    
    # Test with a simple task
    result = engineer.run_coding_task(
        task="Create a Python script that calculates factorial of a number",
        filepath="/workspace/factorial.py"
    )
    
    print("\n" + "="*60)
    print("RESULT")
    print("="*60)
    print(f"Success: {result['success']}")
    print(f"Iterations: {result['iterations']}")
    print(f"\nFiles created:\n{result.get('files_created', 'None')}")


if __name__ == "__main__":
    main()
