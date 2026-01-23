"""
Workspace Management Tool Module
Manage sandboxed workspace for code generation and testing
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from .tool_registry import register_tool
from .file_ops import write_file, read_file, list_directory, delete_file


# Default workspace location
DEFAULT_WORKSPACE = Path.home() / "workspace"


@register_tool(
    name="init_workspace",
    description="Initialize or reset the workspace directory",
    category="workspace",
    examples=[
        "init_workspace()",
        "init_workspace('/custom/workspace')",
        "init_workspace(clean=True)"
    ]
)
def init_workspace(
    workspace_path: Optional[str] = None,
    clean: bool = False
) -> Dict[str, Any]:
    """
    Initialize workspace directory
    
    Args:
        workspace_path: Custom workspace path (default: ~/workspace)
        clean: Remove existing workspace if it exists
    
    Returns:
        dict with 'success', 'path'
    """
    try:
        workspace = Path(workspace_path) if workspace_path else DEFAULT_WORKSPACE
        workspace = workspace.expanduser().resolve()
        
        if workspace.exists() and clean:
            shutil.rmtree(workspace)
        
        workspace.mkdir(parents=True, exist_ok=True)
        
        return {
            'success': True,
            'path': str(workspace),
            'exists': True,
            'cleaned': clean
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="get_workspace_path",
    description="Get the current workspace path",
    category="workspace",
    examples=[
        "get_workspace_path()"
    ]
)
def get_workspace_path(workspace_path: Optional[str] = None) -> str:
    """
    Get workspace path
    
    Args:
        workspace_path: Custom workspace path (default: ~/workspace)
    
    Returns:
        Absolute workspace path as string
    """
    workspace = Path(workspace_path) if workspace_path else DEFAULT_WORKSPACE
    return str(workspace.expanduser().resolve())


@register_tool(
    name="save_to_workspace",
    description="Save content to a file in the workspace",
    category="workspace",
    examples=[
        "save_to_workspace('script.py', code_content)",
        "save_to_workspace('data/config.json', json_data)",
        "save_to_workspace('test.py', code, workspace='/custom/path')"
    ]
)
def save_to_workspace(
    filename: str,
    content: str,
    workspace_path: Optional[str] = None,
    subdirectory: Optional[str] = None
) -> Dict[str, Any]:
    """
    Save file to workspace
    
    Args:
        filename: Name of file to save
        content: File content
        workspace_path: Custom workspace path
        subdirectory: Optional subdirectory within workspace
    
    Returns:
        dict with 'success', 'filepath'
    """
    try:
        workspace = Path(get_workspace_path(workspace_path))
        
        # Ensure workspace exists
        workspace.mkdir(parents=True, exist_ok=True)
        
        # Build full path
        if subdirectory:
            filepath = workspace / subdirectory / filename
        else:
            filepath = workspace / filename
        
        # Write file
        result = write_file(str(filepath), content)
        
        return result
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="read_from_workspace",
    description="Read a file from the workspace",
    category="workspace",
    examples=[
        "read_from_workspace('script.py')",
        "read_from_workspace('data/config.json')"
    ]
)
def read_from_workspace(
    filename: str,
    workspace_path: Optional[str] = None,
    subdirectory: Optional[str] = None
) -> Dict[str, Any]:
    """
    Read file from workspace
    
    Args:
        filename: Name of file to read
        workspace_path: Custom workspace path
        subdirectory: Optional subdirectory within workspace
    
    Returns:
        dict with 'success', 'content'
    """
    try:
        workspace = Path(get_workspace_path(workspace_path))
        
        # Build full path
        if subdirectory:
            filepath = workspace / subdirectory / filename
        else:
            filepath = workspace / filename
        
        return read_file(str(filepath))
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="list_workspace",
    description="List all files in the workspace",
    category="workspace",
    examples=[
        "list_workspace()",
        "list_workspace(pattern='*.py')",
        "list_workspace(subdirectory='tests')"
    ]
)
def list_workspace(
    workspace_path: Optional[str] = None,
    pattern: str = "*",
    subdirectory: Optional[str] = None,
    recursive: bool = False
) -> Dict[str, Any]:
    """
    List workspace contents
    
    Args:
        workspace_path: Custom workspace path
        pattern: Glob pattern to filter
        subdirectory: Optional subdirectory
        recursive: Search recursively
    
    Returns:
        dict with 'success', 'files', 'directories'
    """
    try:
        workspace = Path(get_workspace_path(workspace_path))
        
        if subdirectory:
            workspace = workspace / subdirectory
        
        return list_directory(str(workspace), pattern=pattern, recursive=recursive)
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="clean_workspace",
    description="Remove all files from workspace",
    category="workspace",
    examples=[
        "clean_workspace()",
        "clean_workspace(pattern='*.tmp')",
        "clean_workspace(confirm=True)"
    ]
)
def clean_workspace(
    workspace_path: Optional[str] = None,
    pattern: Optional[str] = None,
    confirm: bool = False
) -> Dict[str, Any]:
    """
    Clean workspace directory
    
    Args:
        workspace_path: Custom workspace path
        pattern: Only delete files matching pattern (if None, delete all)
        confirm: Must be True to actually delete
    
    Returns:
        dict with 'success', 'deleted_count'
    """
    if not confirm:
        return {
            'success': False,
            'error': 'Must set confirm=True to delete files'
        }
    
    try:
        workspace = Path(get_workspace_path(workspace_path))
        
        if not workspace.exists():
            return {
                'success': True,
                'deleted_count': 0,
                'message': 'Workspace does not exist'
            }
        
        deleted = 0
        
        if pattern:
            # Delete matching files only
            for filepath in workspace.glob(pattern):
                if filepath.is_file():
                    delete_file(str(filepath))
                    deleted += 1
        else:
            # Delete entire workspace
            shutil.rmtree(workspace)
            workspace.mkdir(parents=True, exist_ok=True)
            deleted = -1  # Indicate full clean
        
        return {
            'success': True,
            'deleted_count': deleted,
            'workspace': str(workspace)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="workspace_stats",
    description="Get statistics about workspace contents",
    category="workspace",
    examples=[
        "workspace_stats()",
        "workspace_stats('/custom/workspace')"
    ]
)
def workspace_stats(workspace_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get workspace statistics
    
    Args:
        workspace_path: Custom workspace path
    
    Returns:
        dict with file counts, total size, file types
    """
    try:
        workspace = Path(get_workspace_path(workspace_path))
        
        if not workspace.exists():
            return {
                'success': True,
                'exists': False,
                'path': str(workspace)
            }
        
        # Count files and sizes
        total_files = 0
        total_dirs = 0
        total_size = 0
        file_types = {}
        
        for item in workspace.rglob('*'):
            if item.is_file():
                total_files += 1
                total_size += item.stat().st_size
                
                # Track file types
                ext = item.suffix or 'no_extension'
                file_types[ext] = file_types.get(ext, 0) + 1
            
            elif item.is_dir():
                total_dirs += 1
        
        return {
            'success': True,
            'exists': True,
            'path': str(workspace),
            'total_files': total_files,
            'total_directories': total_dirs,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_types': file_types
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
