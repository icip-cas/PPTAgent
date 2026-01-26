"""
Pytest configuration and fixtures for sandbox testing.
"""

import json
import sys
from pathlib import Path

import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageFunctionToolCall as ToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from deeppresenter.agents.env import AgentEnv
from deeppresenter.utils.config import GLOBAL_CONFIG

# Output directory for test results (permanent storage)
TEST_OUTPUT_DIR = Path(__file__).parent / "test_outputs"


@pytest.fixture(scope="session")
def test_output_dir():
    """Return the test outputs directory path (permanent storage)."""
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_OUTPUT_DIR


@pytest.fixture
async def workspace(tmp_path, request):
    """Create a temporary workspace for testing.

    By default uses pytest's tmp_path (temporary).
    To use permanent storage, run with: pytest --output-dir=permanent
    """
    use_permanent = request.config.getoption("--output-dir", "temp") == "permanent"

    if use_permanent:
        # Use permanent output directory
        workspace = TEST_OUTPUT_DIR / request.node.name
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        # Use temporary directory (default)
        workspace = tmp_path / "test_workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    return workspace


@pytest.fixture
async def agent_env(workspace):
    """Create an AgentEnv instance with sandbox connection.

    Reads from mcp.json but filters to only load desktop_commander for testing.
    This avoids duplicating configuration while keeping tests focused on sandbox.
    """
    # Read the main MCP config
    mcp_config_path = Path(__file__).parent.parent / "deeppresenter" / "mcp.json"
    with open(mcp_config_path, encoding="utf-8") as f:
        all_servers = json.load(f)

    # Filter to only desktop_commander for testing
    test_servers = [s for s in all_servers if s["name"] == "desktop_commander"]

    if not test_servers:
        raise ValueError("desktop_commander not found in mcp.json")

    # Write filtered config to a temporary file
    test_mcp_path = Path(__file__).parent / ".mcp_test_temp.json"
    with open(test_mcp_path, "w", encoding="utf-8") as f:
        json.dump(test_servers, f, indent=4)

    try:
        # Use filtered config
        test_config = GLOBAL_CONFIG.model_copy(deep=False)
        test_config.mcp_config_file = str(test_mcp_path)

        async with AgentEnv(workspace, test_config) as env:
            # Verify desktop_commander tool is available
            assert "execute_command" in env._tools_dict, (
                "execute_command tool not available - sandbox may not be connected"
            )
            yield env
    finally:
        # Clean up temporary file
        if test_mcp_path.exists():
            test_mcp_path.unlink()


@pytest.fixture
def matplotlib_basic_script():
    """Return a basic matplotlib test script."""
    return """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Create a simple plot
x = [1, 2, 3, 4, 5]
y = [2, 4, 6, 8, 10]

plt.figure(figsize=(8, 6))
plt.plot(x, y, marker='o', linestyle='-', color='blue', linewidth=2)
plt.title('Basic Line Plot')
plt.xlabel('X Axis')
plt.ylabel('Y Axis')
plt.grid(True, alpha=0.3)
plt.savefig('basic_plot.png', dpi=100, bbox_inches='tight')
print('SUCCESS: basic_plot.png generated')
"""


@pytest.fixture
def matplotlib_chinese_script():
    """Return a matplotlib script with Chinese text."""
    return """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Configure Chinese fonts
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# Create plot with Chinese text
categories = ['一月', '二月', '三月', '四月', '五月']
values = [65, 78, 82, 90, 88]

plt.figure(figsize=(10, 6))
plt.bar(categories, values, color='steelblue', alpha=0.8)
plt.title('销售数据统计 - 中文测试', fontsize=16, fontweight='bold')
plt.xlabel('月份', fontsize=12)
plt.ylabel('销售额（万元）', fontsize=12)
plt.grid(axis='y', alpha=0.3)

# Add value labels on bars
for i, v in enumerate(values):
    plt.text(i, v + 1, str(v), ha='center', va='bottom')

plt.tight_layout()
plt.savefig('chinese_plot.png', dpi=100, bbox_inches='tight')
print('SUCCESS: chinese_plot.png generated')
"""


@pytest.fixture
def matplotlib_complex_script():
    """Return a complex matplotlib script with multiple subplots."""
    return """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# Configure Chinese fonts
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# Create figure with subplots
fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 10))

# Subplot 1: Line plot
x = np.linspace(0, 10, 100)
ax1.plot(x, np.sin(x), label='sin(x)', color='blue')
ax1.plot(x, np.cos(x), label='cos(x)', color='red')
ax1.set_title('三角函数图像', fontsize=12, fontweight='bold')
ax1.set_xlabel('x轴')
ax1.set_ylabel('y轴')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Subplot 2: Bar chart
categories = ['产品A', '产品B', '产品C', '产品D']
values = [23, 45, 56, 78]
ax2.bar(categories, values, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A'])
ax2.set_title('产品销量对比', fontsize=12, fontweight='bold')
ax2.set_ylabel('销量')

# Subplot 3: Scatter plot
x_scatter = np.random.randn(50)
y_scatter = np.random.randn(50)
colors = np.random.rand(50)
ax3.scatter(x_scatter, y_scatter, c=colors, s=100, alpha=0.6, cmap='viridis')
ax3.set_title('散点图示例', fontsize=12, fontweight='bold')
ax3.set_xlabel('特征1')
ax3.set_ylabel('特征2')

# Subplot 4: Pie chart
sizes = [30, 25, 20, 25]
labels = ['类别一', '类别二', '类别三', '类别四']
colors_pie = ['#FF9999', '#66B2FF', '#99FF99', '#FFCC99']
ax4.pie(sizes, labels=labels, colors=colors_pie, autopct='%1.1f%%', startangle=90)
ax4.set_title('数据分布饼图', fontsize=12, fontweight='bold')

plt.tight_layout()
plt.savefig('complex_plot.png', dpi=100, bbox_inches='tight')
print('SUCCESS: complex_plot.png generated')
"""


@pytest.fixture
def mermaid_basic_diagram():
    """Return a basic mermaid flowchart."""
    return """flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Action 1]
    B -->|No| D[Action 2]
    C --> E[End]
    D --> E
"""


@pytest.fixture
def mermaid_chinese_diagram():
    """Return a mermaid diagram with Chinese text."""
    return """flowchart TD
    A[开始] --> B{判断条件}
    B -->|满足条件| C[执行操作A]
    B -->|不满足| D[执行操作B]
    C --> E[记录日志]
    D --> E
    E --> F[结束]

    style A fill:#e1f5ff
    style F fill:#e1f5ff
    style B fill:#fff9c4
    style C fill:#c8e6c9
    style D fill:#ffccbc
"""


@pytest.fixture
def mermaid_sequence_diagram():
    """Return a mermaid sequence diagram with Chinese text."""
    return """sequenceDiagram
    participant 用户
    participant 前端
    participant 后端
    participant 数据库

    用户->>前端: 提交请求
    前端->>后端: 发送API调用
    后端->>数据库: 查询数据
    数据库-->>后端: 返回结果
    后端-->>前端: 返回JSON数据
    前端-->>用户: 显示结果
"""


def create_tool_call(tool_name: str, arguments: dict, call_id: str = None) -> ToolCall:
    """Helper function to create a ToolCall object."""
    if call_id is None:
        import uuid

        call_id = f"call_{uuid.uuid4().hex[:8]}"

    return ToolCall(
        id=call_id,
        type="function",
        function=Function(
            name=tool_name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )


@pytest.fixture
def tool_call_helper():
    """Return the tool call helper function."""
    return create_tool_call


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--output-dir",
        action="store",
        default="temp",
        choices=["temp", "permanent"],
        help="Choose output directory: temp (default, auto-cleanup) or permanent (keep all results)",
    )
