"""
Test matplotlib with the most complex scenario.
"""

import pytest


class TestMatplotlibAdvanced:
    """Test matplotlib with the most complex scenario."""

    @pytest.mark.asyncio
    async def test_matplotlib_complex_chinese(
        self, agent_env, workspace, matplotlib_complex_script, tool_call_helper
    ):
        """Test complex matplotlib: 4 subplots + Chinese text + multiple chart types."""
        script_path = workspace / "test_complex.py"
        write_call = tool_call_helper(
            "write_file",
            {"path": str(script_path), "content": matplotlib_complex_script},
        )
        write_result = await agent_env.tool_execute(write_call)
        assert not write_result.is_error, f"Failed to write script: {write_result.text}"

        # Execute the script
        exec_call = tool_call_helper(
            "execute_command",
            {"command": f"python {script_path}"},
        )
        exec_result = await agent_env.tool_execute(exec_call)
        assert not exec_result.is_error, f"Script execution failed: {exec_result.text}"
        assert "SUCCESS" in exec_result.text, (
            f"Script did not report success: {exec_result.text}"
        )

        # Verify the output file exists
        list_call = tool_call_helper(
            "list_directory",
            {"path": str(workspace)},
        )
        list_result = await agent_env.tool_execute(list_call)
        assert "complex_plot.png" in list_result.text, "Complex plot not found"
