# Step-by-Step: What We Did and Where to Find Artifacts

## Overview

We set up PPTAgent to generate presentations using OpenRouter API, then ran a test that successfully created a 6-slide presentation.

---

## Step 1: Added OpenRouter Support 🔌

### What We Did:

- Modified `pptagent/model_utils.py` to detect `OPEN_ROUTER_API_KEY` environment variable
- Added automatic `.env` file loading using `python-dotenv`
- Configured the system to use OpenRouter API (`https://openrouter.ai/api/v1`) when OpenRouter key is present
- Updated default model names to use OpenRouter-compatible formats

### Files Modified:

- `pptagent/model_utils.py` - Added OpenRouter detection and API configuration
- `pptagent/llms.py` - Improved error logging for connection tests
- `pyproject.toml` - Added `python-dotenv` dependency

### Artifacts:

- **Configuration**: `.env` file (in project root, gitignored)
  - Contains: `OPEN_ROUTER_API_KEY`, `LANGUAGE_MODEL`, `VISION_MODEL`

---

## Step 2: Environment Setup ⚙️

### What We Did:

- Created Python virtual environment with Python 3.12
- Installed all project dependencies including full optional dependencies
- Configured `.env` file with:
  - `OPEN_ROUTER_API_KEY` - Your OpenRouter API key
  - `LANGUAGE_MODEL=openai/gpt-4o` - For text generation (supports structured outputs)
  - `VISION_MODEL=openai/gpt-4o` - For image/slide analysis

### Files Created:

- `venv/` - Python virtual environment directory
- `.env` - Environment configuration (gitignored, contains API keys)

### Why These Models?

- **gpt-4o** supports structured outputs (JSON schema) which PPTAgent requires
- **gpt-4o** also has vision capabilities, so it works for both text and image tasks

---

## Step 3: Test Script Execution 🧪

### What We Did:

Ran `test_generate_presentation.py` which:

1. **Loaded Pre-processed Data** (from `runs/` directory):

   - Template: `runs/pptx/default_template/`
   - Document: `runs/pdf/57b32a38d68d1e62908a3d4fe77441c2/`

2. **Initialized Models**:

   - Connected to OpenRouter API
   - Tested connections to language and vision models

3. **Loaded Template**:

   - PowerPoint template: `runs/pptx/default_template/source.pptx`
   - Slide induction data: `runs/pptx/default_template/slide_induction.json`
   - Image statistics: `runs/pptx/default_template/image_stats.json`

4. **Loaded Document**:

   - Pre-processed document JSON: `runs/pdf/57b32a38d68d1e62908a3d4fe77441c2/refined_doc.json`
   - Contains structured content from PDF about "Building Effective Agents"

5. **Generated Presentation**:

   - Created 6 slides based on the document content
   - Used the template's layout patterns
   - Applied image statistics for visual consistency

6. **Saved Output**:
   - Final presentation: `test_output.pptx` (197KB, 6 slides)

---

## Where to Find Artifacts 📁

### Input Data (Pre-processed):

#### Template Data:

```
runs/pptx/default_template/
├── source.pptx                    # Original PowerPoint template (INPUT)
├── slide_induction.json           # Generated from source.pptx - Extracted slide layouts and schemas
├── image_stats.json               # Generated from source.pptx - Image captions and statistics
├── images/                        # Extracted images from template
│   ├── 0237c4089461afe65b4e235bffbcab3ecdd574fb.png
│   └── ...
├── slide_images/                  # Rendered slide images
│   ├── slide_0001.jpg
│   └── ...
└── template_images/               # Normalized template images
    ├── slide_0001.jpg
    └── ...
```

#### Document Data:

```
runs/pdf/57b32a38d68d1e62908a3d4fe77441c2/
├── source.pdf                     # Original PDF document (INPUT)
├── source.md                      # Generated from source.pdf - Markdown version
├── refined_doc.json               # Generated from source.md - Structured document with sections
└── *.jpg                          # Extracted images from PDF
    ├── 4975736f1d52fb8b7d61d968f910f145ed002b9b37724211f2d4eb212fef5fbb.jpg
    └── ...
```

### Output:

#### Generated Presentation:

```
test_output.pptx                   # Final generated presentation (197KB, 6 slides)
```

### Configuration Files:

#### Environment:

```
.env                               # API keys and model configuration (gitignored)
```

#### Code Changes:

```
pptagent/model_utils.py            # OpenRouter support
pptagent/llms.py                   # Improved error handling
test_generate_presentation.py     # Test script
TESTING.md                         # Testing documentation
VISION_MODELS.md                   # Vision model explanation
```

---

## The Generation Process (What Happens Internally) 🔄

### Phase 1: Template Analysis (Already Done)

The template (`source.pptx`) was pre-analyzed and the results stored in JSON files:

**How `slide_induction.json` is Generated:**

1. Load `source.pptx` as a Presentation object
2. Convert slides to images (`slide_images/` and `template_images/`)
3. Use **vision models** to analyze slide images and group similar layouts
4. Use **language models** to extract content schemas (what text/elements go where)
5. Save the layout patterns and content schemas to `slide_induction.json`

**How `image_stats.json` is Generated:**

1. Extract all images from `source.pptx`
2. Use **vision models** to generate captions for each image
3. Collect metadata: image size, position, which slides they appear on
4. Save image captions and statistics to `image_stats.json`

**Tools Used:**

- `SlideInducter` class (`pptagent/induct.py`) - Analyzes slide layouts and content
- `ImageLabler` class (`pptagent/multimodal.py`) - Captions images
- Vision models - Analyze visual content
- Language models - Extract structured schemas

### Phase 2: Document Processing (Already Done)

The PDF (`source.pdf`) was pre-processed through multiple steps:

**Step 1: PDF Parsing (creates `source.md`):**

1. Uses **MinerU API** (or similar PDF parser) to extract text and images from PDF
2. Converts PDF content to Markdown format
3. Extracts images and saves them as separate `.jpg` files
4. Saves markdown to `source.md`

**Step 2: Document Refinement (creates `refined_doc.json`):**

1. Loads `source.md` markdown content
2. Uses **language models** (`doc_extractor` agent) to:
   - Identify sections and subsections from headings
   - Extract metadata (title, author, date, organization)
   - Generate summaries for each section
   - Structure content into hierarchical format
3. Uses **vision models** to caption extracted images
4. Organizes everything into a structured `Document` object
5. Saves to `refined_doc.json` with:
   - Metadata (title, author, date, etc.)
   - Sections with titles and summaries
   - Subsections with content
   - Image references and captions

**Tools Used:**

- `parse_pdf()` function (`pptagent/model_utils.py`) - Parses PDF using MinerU API
- `Document.from_markdown()` (`pptagent/document/document.py`) - Structures markdown content
- `doc_extractor` agent - Extracts structured content using LLMs
- Vision models - Caption images from PDF

### Phase 3: Presentation Generation (What Just Ran)

1. **Outline Generation**: Creates presentation structure from document
2. **Layout Selection**: Chooses appropriate slide layouts from template
3. **Content Organization**: Organizes document content into slides
4. **Slide Editing**: Uses AI agents to edit slides with proper content
5. **Image Integration**: Places relevant images from document
6. **Final Assembly**: Combines everything into final PowerPoint

### Interim Artifacts (During Generation)

If you run the full pipeline (not just the test), you'd find:

```
runs/{task_id}/
├── task.json                      # Task configuration
├── template.pptx                  # Template copy
├── template_images/               # Rendered template slides
├── images/                        # Extracted images
└── final.pptx                     # Generated presentation
```

---

## Key Files Explained 📄

### `slide_induction.json`

Contains the "DNA" of the template:

- Which slides use which layouts
- What content schema each layout expects
- Functional slide types (opening, TOC, section, ending)

### `refined_doc.json`

Structured representation of the source document:

- Metadata (title, author, date)
- Sections with titles and summaries
- Content blocks with text
- Image references

### `image_stats.json`

Image metadata for the template:

- Captions for each image
- Size and position information
- Where images appear in the presentation

---

## Next Steps 🚀

### To Generate More Presentations:

1. **Use Different Documents**:

   - Process a new PDF (requires MinerU API for PDF parsing)
   - Or use existing pre-processed documents in `runs/pdf/`

2. **Use Different Templates**:

   - Use templates from `pptagent/templates/` (beamer, cip, hit, thu, ucas)
   - Or use your own template

3. **Modify Test Script**:

   - Change `num_slides` parameter
   - Use different document/template paths
   - Adjust retry settings

4. **Use the Web UI**:
   - Run `python pptagent_ui/backend.py` for the backend
   - Run `npm run serve` in `pptagent_ui/` for the frontend
   - Upload PDFs and templates through the web interface

---

## Troubleshooting 🔧

### If You Want to See More Details:

- Check logs: The script prints progress messages
- Enable debug mode: Set `LOG_LEVEL=DEBUG` in `.env`
- Check model responses: Some intermediate data may be logged

### If Generation Fails:

- Check API key is valid in `.env`
- Verify model names are correct for OpenRouter
- Ensure models support structured outputs (gpt-4o, gpt-4-turbo, etc.)

---

## Summary ✅

**What We Accomplished:**

1. ✅ Added OpenRouter API support
2. ✅ Configured environment with API keys and models
3. ✅ Set up Python environment with all dependencies
4. ✅ Successfully generated a test presentation
5. ✅ Created documentation for future use

**Final Output:**

- `test_output.pptx` - Your generated presentation (6 slides, 197KB)

**Key Takeaway:**
The system uses pre-processed templates and documents to generate presentations. The actual generation happens in memory, but you can find all input data in the `runs/` directory and the final output in the project root.
