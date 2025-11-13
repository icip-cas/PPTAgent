# Testing Guide for PPTAgent

This guide explains how to test PPTAgent and generate presentations.

## Prerequisites

1. **Environment Variables**: Set up your API keys and model configuration (can be in `.env` file):

   ```bash
   # Option 1: Use OpenRouter (recommended - supports many models)
   export OPEN_ROUTER_API_KEY="your-openrouter-api-key"
   export LANGUAGE_MODEL="openai/gpt-4"  # OpenRouter format
   export VISION_MODEL="openai/gpt-4-vision-preview"

   # Option 2: Use OpenAI directly
   export OPENAI_API_KEY="your-openai-api-key"
   export LANGUAGE_MODEL="gpt-4.1"  # Optional, defaults to "gpt-4.1"
   export VISION_MODEL="gpt-4.1"    # Optional, defaults to "gpt-4.1"

   # Optional: Custom API base URL
   export API_BASE="http://your-service-provider/v1"
   ```

   **Note**: You can create a `.env` file in the project root with these variables, and it will be automatically loaded.

2. **Pre-processed Data**: The test uses pre-processed data from:
   - Template: `runs/pptx/default_template/`
   - Document: `runs/pdf/57b32a38d68d1e62908a3d4fe77441c2/`

## Quick Test: Generate a Presentation

### Option 1: Using the Test Script

Run the standalone test script:

```bash
python test_generate_presentation.py
```

This will:

1. Initialize models and test connections
2. Load a pre-processed template and document
3. Generate a 5-slide presentation
4. Save it to `test_output.pptx`

### Option 2: Using pytest

Run the existing test suite:

```bash
# Run all tests (excluding LLM tests)
pytest test/ -v

# Run only LLM tests (requires API keys)
pytest test/ -v -m llm

# Run specific test
pytest test/test_pptgen.py -v -m llm
```

The `test_pptgen.py` test generates a 3-slide presentation using the pre-processed data.

## Understanding the Test Structure

### Test Configuration (`test/conftest.py`)

The test configuration loads:

- **Template**: PowerPoint template with slide layouts
- **Document**: Pre-processed document JSON with sections and content
- **Models**: Language and vision models from environment variables

### Test Flow

1. **Load Template**: Loads the PowerPoint template and slide induction data
2. **Load Document**: Loads the pre-processed document JSON
3. **Initialize PPTAgent**: Sets up the agent with language and vision models
4. **Set Reference**: Configures the agent with template and slide patterns
5. **Generate**: Creates slides based on the document content

## Code Structure

### Main Components

- **`PPTAgent`** (`pptagent/pptgen.py`): Main class for generating presentations
- **`Document`** (`pptagent/document/document.py`): Represents the source document
- **`Presentation`** (`pptagent/presentation/presentation.py`): Represents the PowerPoint file
- **`ModelManager`** (`pptagent/model_utils.py`): Manages LLM model connections

### Example Usage

```python
import asyncio
from pptagent.pptgen import PPTAgent
from pptagent.document import Document
from pptagent.presentation import Presentation
from pptagent.model_utils import ModelManager
from pptagent.utils import Config

async def generate():
    # Initialize models
    models = ModelManager()

    # Load template
    config = Config("runs/pptx/default_template")
    presentation = Presentation.from_file(
        "runs/pptx/default_template/source.pptx",
        config
    )

    # Load document
    document = Document(**json.load(open("document.json")))

    # Create agent
    agent = PPTAgent(
        language_model=models.language_model,
        vision_model=models.vision_model,
    )
    agent.set_reference(
        slide_induction=slide_induction,
        presentation=presentation,
    )

    # Generate
    result, _ = await agent.generate_pres(document, num_slides=5)
    result.save("output.pptx")

asyncio.run(generate())
```

## Troubleshooting

### Model Connection Errors

If you see connection errors:

1. Check `OPENAI_API_KEY` is set correctly
2. Verify `API_BASE` if using a custom endpoint
3. Ensure the model names are correct for your provider

### Missing Pre-processed Data

If test data is missing:

- The template data should be in `runs/pptx/default_template/`
- The document data should be in `runs/pdf/57b32a38d68d1e62908a3d4fe77441c2/`
- You can pre-process your own data using the induction scripts

### Import Errors

Make sure the package is installed:

```bash
pip install -e ".[full]"
```

## Next Steps

- See `DOC.md` for full documentation
- See `BESTPRACTICE.md` for best practices
- Check `test/` directory for more test examples
