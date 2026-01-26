"""
Integration tests for sandbox environment.
"""

import pytest


class TestIntegration:
    """Integration tests for sandbox environment."""

    @pytest.mark.asyncio
    async def test_all_tools_available(self, agent_env):
        """Verify all required sandbox tools are available."""
        required_tools = {
            "MCP Tools": [
                "execute_command",
                "write_file",
                "read_file",
                "list_directory",
                "create_directory",
                "move_file",
                "edit_file",
            ],
        }

        available_tools = list(agent_env._tools_dict.keys())

        for category, tools in required_tools.items():
            for tool in tools:
                assert tool in available_tools, (
                    f"Required tool '{tool}' not available in {category}"
                )

        print(
            f"\n✓ All {sum(len(v) for v in required_tools.values())} required tools available"
        )

    @pytest.mark.asyncio
    async def test_environment_capabilities(
        self, agent_env, workspace, tool_call_helper
    ):
        """Test that all key libraries and tools are working."""
        test_script = """
import sys
print("=== Python Environment ===")
print(f"Python: {sys.version.split()[0]}")

# Test data science imports
import numpy as np
import pandas as pd
import matplotlib
import seaborn as sns
import plotly
print(f"NumPy: {np.__version__}")
print(f"Pandas: {pd.__version__}")
print(f"Matplotlib: {matplotlib.__version__}")
print(f"Seaborn: {sns.__version__}")
print(f"Plotly: {plotly.__version__}")

# Test image processing imports
import cv2
from PIL import Image
print(f"OpenCV: {cv2.__version__}")
print(f"Pillow: {Image.__version__}")

# Test document generation
from pptx import Presentation
print(f"python-pptx: Available")

print("\\n✓ All libraries loaded successfully")
"""
        write_call = tool_call_helper(
            "write_file",
            {"path": str(workspace / "test_env.py"), "content": test_script},
        )
        await agent_env.tool_execute(write_call)

        exec_call = tool_call_helper(
            "execute_command",
            {"command": f"python {workspace / 'test_env.py'}"},
        )
        result = await agent_env.tool_execute(exec_call)
        assert not result.is_error, f"Environment test failed: {result.text}"
        assert "All libraries loaded successfully" in result.text

        # Test system tools - all should be available in sandbox
        system_tools = [
            ("git --version", "git version"),
            ("mmdc --version", ""),  # mmdc might not output to stdout
            ("rg --version", "ripgrep"),
            ("convert --version", "ImageMagick"),
        ]

        for cmd, expected in system_tools:
            tool_call = tool_call_helper("execute_command", {"command": cmd})
            result = await agent_env.tool_execute(tool_call)
            # Assert that critical tools are available
            tool_name = cmd.split()[0]
            assert not (result.is_error and "not found" in result.text), (
                f"Critical system tool '{tool_name}' not available in sandbox"
            )

            # Verify expected output if specified
            if expected and not result.is_error:
                assert expected in result.text, (
                    f"Tool '{tool_name}' found but output unexpected: {result.text[:100]}"
                )
