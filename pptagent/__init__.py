"""PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides.

This package provides tools to automatically generate presentations from documents,
following a two-phase approach of Analysis and Generation.

For more information, visit: https://github.com/icip-cas/PPTAgent
"""

__version__ = "0.1.0"
__author__ = "Hao Zheng"
__email__ = "wszh712811@gmail.com"

# Import main modules to make them directly accessible when importing the package
from .agent import *
from .apis import *
from .document import *
from .induct import *
from .layout import *
from .llms import *
from .model_utils import *
from .multimodal import *
from .pptgen import *
from .presentation import *
from .shapes import *
from .utils import *

# Define the top-level exports
__all__ = [
    "agent",
    "pptgen",
    "document",
    "llms",
    "presentation",
    "utils",
    "shapes",
    "layout",
    "apis",
    "model_utils",
    "multimodal",
    "induct",
]
