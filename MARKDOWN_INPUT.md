# Using Markdown as Input

Yes! PPTAgent can work with **markdown files directly** - you don't need to start with a PDF.

## How It Works

The system has two paths:

### Path 1: PDF → Markdown → Structured JSON

1. PDF is parsed using MinerU API → creates `source.md`
2. Markdown is processed → creates `refined_doc.json`

### Path 2: Markdown → Structured JSON (Direct)

1. Provide markdown content directly
2. Markdown is processed → creates `refined_doc.json`

## The Core Function

The key function is `Document.from_markdown()` which accepts markdown content directly:

```python
from pptagent.document import Document
from pptagent.model_utils import ModelManager

models = ModelManager()

# Read your markdown file
with open("my_document.md", "r", encoding="utf-8") as f:
    markdown_content = f.read()

# Process it directly (no PDF needed!)
document = await Document.from_markdown(
    markdown_content,
    models.language_model,
    models.vision_model,
    image_dir="path/to/images"  # Where images referenced in markdown are stored
)
```

## Current Backend Behavior

Looking at `pptagent_ui/backend.py`:

```python
# pdf parsing
if not os.path.exists(join(parsedpdf_dir, "source.md")):
    text_content = parse_pdf(...)  # Only parses if markdown doesn't exist
else:
    text_content = open(join(parsedpdf_dir, "source.md"), encoding="utf-8").read()
    # Uses existing markdown directly!
```

So if you place a `source.md` file in the document directory, it will skip PDF parsing entirely!

## How to Use Markdown Directly

### Option 1: Pre-create `source.md`

1. Create your markdown file
2. Place it in: `runs/pdf/{hash}/source.md`
3. Place any images referenced in markdown in the same directory
4. Run the generation - it will skip PDF parsing

### Option 2: Modify the Test Script

You can modify `test_generate_presentation.py` to load markdown directly:

```python
# Instead of loading from refined_doc.json, create from markdown:
with open("my_document.md", "r", encoding="utf-8") as f:
    markdown_content = f.read()

document = await Document.from_markdown(
    markdown_content,
    models.language_model,
    models.vision_model,
    image_dir="path/to/images"
)
```

### Option 3: Use the Document Class Directly

The `Document.from_markdown()` method is the core - it doesn't care where the markdown came from!

## Markdown Format Requirements

The markdown should:

- Use headings (`#`, `##`, `###`) to structure sections
- Reference images: `![alt text](image.jpg)`
- Include tables in markdown format
- Can include metadata in the content (title, author, etc.)

## Example Workflow with Markdown

```python
import asyncio
from pptagent.document import Document
from pptagent.model_utils import ModelManager
from pptagent.pptgen import PPTAgent
from pptagent.presentation import Presentation
from pptagent.utils import Config

async def generate_from_markdown():
    models = ModelManager()

    # Load markdown directly
    with open("my_presentation.md", "r") as f:
        markdown = f.read()

    # Create document from markdown
    document = await Document.from_markdown(
        markdown,
        models.language_model,
        models.vision_model,
        image_dir="images/"  # Where your images are
    )

    # Continue with presentation generation...
    # (rest of the process is the same)
```

## Benefits of Using Markdown

1. **No PDF Parser Needed**: Skip MinerU API requirement
2. **More Control**: You control the exact markdown structure
3. **Faster**: No PDF parsing step
4. **Version Control Friendly**: Markdown is text-based
5. **Easier Editing**: Edit markdown directly instead of PDFs

## Summary

✅ **Yes, markdown works directly!**

The system is designed to work with markdown as the intermediate format. PDF parsing is just one way to get markdown. You can:

- Provide markdown directly
- Skip the PDF parsing step
- Use `Document.from_markdown()` directly in your code

The key insight: **PDF → Markdown → JSON** but you can start at any step!
