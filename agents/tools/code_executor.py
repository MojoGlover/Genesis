"""
Code Executor Tool Module
Safely execute Python code, capture output, handle errors, and support iterative testing
"""

import subprocess
import sys
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from .tool_registry import register_tool


@register_tool(
    name="execute_python",
    description="Execute Python code and capture output/errors",
    category="code_execution",
    examples=[
        "execute_python('print(\"Hello World\")')",
        "execute_python(code, timeout=10)",
        "execute_python(code, working_dir='/workspace')"
    ]
)
def execute_python(
    code: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
    capture_output: bool = True
) -> Dict[str, Any]:
    """
    Execute Python code in a subprocess
    
    Args:
        code: Python code to execute
        timeout: Maximum execution time in seconds
        working_dir: Working directory for execution
        capture_output: Capture stdout/stderr
    
    Returns:
        dict with 'success', 'stdout', 'stderr', 'exit_code', 'error'
    """
    try:
        # Create temporary file for code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        try:
            # Execute
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=working_dir
            )
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout if capture_output else '',
                'stderr': result.stderr if capture_output else '',
                'exit_code': result.returncode,
                'execution_time': timeout  # TODO: track actual time
            }
        
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except:
                pass
    
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': f'Execution timed out after {timeout} seconds',
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }


@register_tool(
    name="execute_file",
    description="Execute a Python file and capture output",
    category="code_execution",
    examples=[
        "execute_file('/workspace/script.py')",
        "execute_file('/workspace/test.py', timeout=60)"
    ]
)
def execute_file(
    filepath: str,
    timeout: int = 30,
    args: List[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Python file
    
    Args:
        filepath: Path to Python file
        timeout: Maximum execution time in seconds
        args: Command line arguments to pass
        working_dir: Working directory for execution
    
    Returns:
        dict with 'success', 'stdout', 'stderr', 'exit_code'
    """
    try:
        filepath = Path(filepath).expanduser().resolve()
        
        if not filepath.exists():
            return {
                'success': False,
                'error': f"File not found: {filepath}"
            }
        
        if not filepath.is_file():
            return {
                'success': False,
                'error': f"Not a file: {filepath}"
            }
        
        # Build command
        cmd = [sys.executable, str(filepath)]
        if args:
            cmd.extend(args)
        
        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir or str(filepath.parent)
        )
        
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode,
            'filepath': str(filepath)
        }
    
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': f'Execution timed out after {timeout} seconds',
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }


@register_tool(
    name="validate_syntax",
    description="Check Python code for syntax errors without executing",
    category="code_execution",
    examples=[
        "validate_syntax('print(\"hello\")')",
        "validate_syntax(code_string)"
    ]
)
def validate_syntax(code: str) -> Dict[str, Any]:
    """
    Validate Python code syntax without executing
    
    Args:
        code: Python code to validate
    
    Returns:
        dict with 'valid', 'error' (if invalid)
    """
    try:
        compile(code, '<string>', 'exec')
        return {
            'valid': True,
            'success': True
        }
    
    except SyntaxError as e:
        return {
            'valid': False,
            'success': False,
            'error': str(e),
            'line': e.lineno,
            'offset': e.offset,
            'text': e.text
        }
    
    except Exception as e:
        return {
            'valid': False,
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="parse_error",
    description="Parse Python error message to extract useful information",
    category="code_execution",
    examples=[
        "parse_error(stderr_output)",
        "parse_error(execution_result['stderr'])"
    ]
)
def parse_error(error_text: str) -> Dict[str, Any]:
    """
    Parse Python error/traceback to extract key information
    
    Args:
        error_text: Error message or traceback
    
    Returns:
        dict with 'error_type', 'message', 'line', 'file', 'traceback'
    """
    try:
        lines = error_text.strip().split('\n')
        
        # Find the last line (usually the error message)
        error_line = lines[-1] if lines else ''
        
        # Extract error type and message
        error_type = ''
        message = error_line
        
        if ':' in error_line:
            parts = error_line.split(':', 1)
            error_type = parts[0].strip()
            message = parts[1].strip() if len(parts) > 1 else ''
        
        # Try to find line number
        line_number = None
        file_path = None
        
        for line in lines:
            if 'File' in line and 'line' in line:
                # Parse: File "path", line X
                try:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        file_part = parts[0].split('"')
                        if len(file_part) >= 2:
                            file_path = file_part[1]
                        
                        line_part = parts[1].strip()
                        if 'line' in line_part:
                            line_number = int(line_part.split()[-1])
                except:
                    pass
        
        return {
            'success': True,
            'error_type': error_type,
            'message': message,
            'line_number': line_number,
            'file_path': file_path,
            'full_traceback': error_text,
            'is_syntax_error': 'SyntaxError' in error_type,
            'is_import_error': 'ImportError' in error_type or 'ModuleNotFoundError' in error_type,
            'is_name_error': 'NameError' in error_type,
            'is_type_error': 'TypeError' in error_type
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'full_traceback': error_text
        }


@register_tool(
    name="test_and_fix_loop",
    description="Execute code, detect errors, and iterate until success or max attempts",
    category="code_execution",
    examples=[
        "test_and_fix_loop(code, max_attempts=5)",
        "test_and_fix_loop(code, fix_callback=my_fixer_function)"
    ]
)
def test_and_fix_loop(
    code: str,
    max_attempts: int = 5,
    timeout: int = 30,
    fix_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Test code and iteratively fix errors
    
    Args:
        code: Initial Python code
        max_attempts: Maximum fix attempts
        timeout: Execution timeout per attempt
        fix_callback: Optional function(code, error_info) -> fixed_code
    
    Returns:
        dict with 'success', 'final_code', 'attempts', 'errors', 'history'
    """
    current_code = code
    history = []
    
    for attempt in range(1, max_attempts + 1):
        # Execute
        result = execute_python(current_code, timeout=timeout)
        
        history.append({
            'attempt': attempt,
            'success': result['success'],
            'stdout': result.get('stdout', ''),
            'stderr': result.get('stderr', ''),
            'code': current_code
        })
        
        if result['success']:
            return {
                'success': True,
                'final_code': current_code,
                'attempts': attempt,
                'history': history
            }
        
        # Parse error
        error_info = parse_error(result.get('stderr', ''))
        
        # Try to fix if callback provided
        if fix_callback and attempt < max_attempts:
            try:
                current_code = fix_callback(current_code, error_info)
            except Exception as e:
                history.append({
                    'attempt': attempt,
                    'fix_error': str(e)
                })
                break
        else:
            break
    
    return {
        'success': False,
        'final_code': current_code,
        'attempts': len(history),
        'history': history,
        'last_error': history[-1] if history else None
    }


@register_tool(
    name="run_shell_command",
    description="Execute a shell command and capture output",
    category="code_execution",
    examples=[
        "run_shell_command('ls -la /workspace')",
        "run_shell_command('pip list')",
        "run_shell_command('git status', working_dir='/genesis')"
    ]
)
def run_shell_command(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
    shell: bool = True
) -> Dict[str, Any]:
    """
    Execute a shell command
    
    Args:
        command: Shell command to execute
        timeout: Maximum execution time
        working_dir: Working directory
        shell: Use shell for execution
    
    Returns:
        dict with 'success', 'stdout', 'stderr', 'exit_code'
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
            shell=shell
        )
        
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode,
            'command': command
        }
    
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': f'Command timed out after {timeout} seconds',
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'stdout': '',
            'stderr': '',
            'exit_code': -1
        }
