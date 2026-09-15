"""Discover and create the file-editing tools used by DEVS-Gen.

For example, ``get_available_tools()`` lists the tools in this package.
Use ``create_tool_instance('see_text_file', working_dir='.')`` to open a
text-file reader for the current directory.
"""

# Import the main functions from tool_registry
from .tool_registry import (
    discover_tools,
    get_available_tools, 
    create_tool_instance,
    get_tool_class,
    get_discovery_errors,
    ToolRegistry
)

# Define what gets imported with "from default_tools import *"
__all__ = [
    'discover_tools',
    'get_available_tools', 
    'create_tool_instance',
    'get_tool_class',
    'get_discovery_errors',
    'ToolRegistry'
]
