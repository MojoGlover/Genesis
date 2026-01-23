"""
Package Manager Tool Module
Handle Python package installation, checking, and management
"""

import subprocess
import sys
import re
from typing import Dict, Any, List, Optional
from .tool_registry import register_tool


@register_tool(
    name="install_package",
    description="Install a Python package using pip",
    category="package_management",
    examples=[
        "install_package('requests')",
        "install_package('numpy==1.24.0')",
        "install_package('flask', upgrade=True)"
    ]
)
def install_package(
    package: str,
    version: Optional[str] = None,
    upgrade: bool = False,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Install a Python package using pip
    
    Args:
        package: Package name
        version: Specific version (e.g., "1.2.3")
        upgrade: Upgrade if already installed
        quiet: Suppress output
    
    Returns:
        dict with 'success', 'package', 'message'
    """
    try:
        # Build package specification
        pkg_spec = package
        if version:
            pkg_spec = f"{package}=={version}"
        
        # Build command
        cmd = [sys.executable, '-m', 'pip', 'install']
        
        if upgrade:
            cmd.append('--upgrade')
        
        if quiet:
            cmd.append('--quiet')
        
        cmd.append(pkg_spec)
        
        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            return {
                'success': True,
                'package': pkg_spec,
                'message': 'Package installed successfully',
                'output': result.stdout
            }
        else:
            return {
                'success': False,
                'package': pkg_spec,
                'error': result.stderr,
                'message': 'Installation failed'
            }
    
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'package': package,
            'error': 'Installation timed out after 120 seconds'
        }
    
    except Exception as e:
        return {
            'success': False,
            'package': package,
            'error': str(e)
        }


@register_tool(
    name="check_package",
    description="Check if a package is installed and get its version",
    category="package_management",
    examples=[
        "check_package('requests')",
        "check_package('numpy')"
    ]
)
def check_package(package: str) -> Dict[str, Any]:
    """
    Check if a package is installed
    
    Args:
        package: Package name
    
    Returns:
        dict with 'installed', 'version', 'location'
    """
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'show', package],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Parse output
            info = {}
            for line in result.stdout.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip().lower()] = value.strip()
            
            return {
                'success': True,
                'installed': True,
                'package': package,
                'version': info.get('version', 'unknown'),
                'location': info.get('location', 'unknown')
            }
        else:
            return {
                'success': True,
                'installed': False,
                'package': package
            }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="list_packages",
    description="List all installed Python packages",
    category="package_management",
    examples=[
        "list_packages()",
        "list_packages(pattern='requests')"
    ]
)
def list_packages(pattern: Optional[str] = None) -> Dict[str, Any]:
    """
    List installed packages
    
    Args:
        pattern: Optional regex pattern to filter packages
    
    Returns:
        dict with 'packages' list
    """
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--format=json'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            import json
            packages = json.loads(result.stdout)
            
            # Filter by pattern if provided
            if pattern:
                regex = re.compile(pattern, re.IGNORECASE)
                packages = [p for p in packages if regex.search(p['name'])]
            
            return {
                'success': True,
                'packages': packages,
                'count': len(packages)
            }
        else:
            return {
                'success': False,
                'error': result.stderr
            }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="extract_imports",
    description="Extract import statements from Python code to identify dependencies",
    category="package_management",
    examples=[
        "extract_imports(code_string)",
        "extract_imports('import requests\\nfrom flask import Flask')"
    ]
)
def extract_imports(code: str) -> Dict[str, Any]:
    """
    Extract import statements from code
    
    Args:
        code: Python code string
    
    Returns:
        dict with 'imports' list and 'packages' list
    """
    try:
        imports = []
        packages = set()
        
        for line in code.split('\n'):
            line = line.strip()
            
            # Match: import package
            if line.startswith('import '):
                parts = line.replace('import ', '').split(',')
                for part in parts:
                    pkg = part.strip().split()[0].split('.')[0]
                    imports.append(line)
                    packages.add(pkg)
            
            # Match: from package import ...
            elif line.startswith('from '):
                parts = line.replace('from ', '').split('import')
                if parts:
                    pkg = parts[0].strip().split('.')[0]
                    imports.append(line)
                    packages.add(pkg)
        
        return {
            'success': True,
            'imports': imports,
            'packages': sorted(list(packages)),
            'count': len(packages)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="check_missing_packages",
    description="Check which packages from code are not installed",
    category="package_management",
    examples=[
        "check_missing_packages(code_string)",
        "check_missing_packages(code, exclude=['os', 'sys'])"
    ]
)
def check_missing_packages(
    code: str,
    exclude: List[str] = None
) -> Dict[str, Any]:
    """
    Check which packages are missing for given code
    
    Args:
        code: Python code string
        exclude: Standard library modules to exclude
    
    Returns:
        dict with 'missing' list and 'installed' list
    """
    try:
        # Standard library modules to ignore
        stdlib = {
            'os', 'sys', 're', 'json', 'time', 'datetime', 'math',
            'random', 'collections', 'itertools', 'functools', 'pathlib',
            'subprocess', 'threading', 'multiprocessing', 'typing',
            'logging', 'argparse', 'configparser', 'urllib', 'http',
            'socket', 'email', 'base64', 'hashlib', 'hmac', 'secrets',
            'tempfile', 'shutil', 'glob', 'fnmatch', 'pickle', 'shelve',
            'csv', 'xml', 'html', 'io', 'struct', 'array', 'copy'
        }
        
        if exclude:
            stdlib.update(exclude)
        
        # Extract imports
        extract_result = extract_imports(code)
        if not extract_result['success']:
            return extract_result
        
        packages = extract_result['packages']
        
        # Filter out stdlib
        third_party = [p for p in packages if p not in stdlib]
        
        # Check each package
        missing = []
        installed = []
        
        for pkg in third_party:
            check_result = check_package(pkg)
            if check_result.get('installed'):
                installed.append(pkg)
            else:
                missing.append(pkg)
        
        return {
            'success': True,
            'missing': missing,
            'installed': installed,
            'total_imports': len(packages),
            'third_party_count': len(third_party)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="auto_install_dependencies",
    description="Automatically install missing packages for given code",
    category="package_management",
    examples=[
        "auto_install_dependencies(code_string)",
        "auto_install_dependencies(code, dry_run=True)"
    ]
)
def auto_install_dependencies(
    code: str,
    dry_run: bool = False,
    quiet: bool = True
) -> Dict[str, Any]:
    """
    Automatically install missing dependencies
    
    Args:
        code: Python code string
        dry_run: Only check, don't install
        quiet: Suppress pip output
    
    Returns:
        dict with 'installed' list and 'failed' list
    """
    try:
        # Check missing packages
        check_result = check_missing_packages(code)
        if not check_result['success']:
            return check_result
        
        missing = check_result['missing']
        
        if not missing:
            return {
                'success': True,
                'message': 'No missing packages',
                'missing': [],
                'installed': [],
                'failed': []
            }
        
        if dry_run:
            return {
                'success': True,
                'message': f'Would install: {", ".join(missing)}',
                'missing': missing,
                'installed': [],
                'failed': []
            }
        
        # Install each package
        installed = []
        failed = []
        
        for pkg in missing:
            result = install_package(pkg, quiet=quiet)
            if result['success']:
                installed.append(pkg)
            else:
                failed.append({
                    'package': pkg,
                    'error': result.get('error', 'Unknown error')
                })
        
        return {
            'success': len(failed) == 0,
            'installed': installed,
            'failed': failed,
            'total_attempted': len(missing)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
