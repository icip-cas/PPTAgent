"""
Merged Sandbox Testing Suite - Main Entry Point

This file serves as a unified entry point to run all sandbox tests.
It imports all test classes from individual test files.

Test categories:
1. Matplotlib: Complex multi-subplot with Chinese text
2. Mermaid: Sequence diagram with Chinese text
3. MCP Tools: Complete workflow (create→edit→move)
4. Data Science: Full visualization pipeline (pandas+numpy+matplotlib+seaborn)
5. Image Processing: OpenCV advanced processing
6. Document Generation: python-pptx with multiple slides
7. System Tools: Ripgrep search with multiple files
8. Integration: Tools availability check

Usage:
    # Run all tests in this suite
    pytest deeppresenter/test/test_sandbox.py -v

    # Run with detailed output
    pytest deeppresenter/test/test_sandbox.py -v -s

    # Run specific test
    pytest deeppresenter/test/test_sandbox.py::TestMatplotlibAdvanced -v

    # Run all tests in the test directory
    pytest deeppresenter/test/ -v
"""

# Import all test classes from individual test files
from test_data_science_pipeline import TestDataSciencePipeline
from test_document_generation import TestDocumentGeneration
from test_image_processing_advanced import TestImageProcessingAdvanced
from test_integration import TestIntegration
from test_matplotlib_advanced import TestMatplotlibAdvanced
from test_mcp_tools_workflow import TestMCPToolsWorkflow
from test_mermaid_advanced import TestMermaidAdvanced
from test_system_tools_advanced import TestSystemToolsAdvanced

# Re-export all test classes so pytest can discover them
__all__ = [
    "TestMatplotlibAdvanced",
    "TestMermaidAdvanced",
    "TestMCPToolsWorkflow",
    "TestDataSciencePipeline",
    "TestImageProcessingAdvanced",
    "TestDocumentGeneration",
    "TestSystemToolsAdvanced",
    "TestIntegration",
]
