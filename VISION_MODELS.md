# Why Vision Models Are Used in PPTAgent

PPTAgent uses **vision models** (multimodal LLMs that can understand images) for several critical tasks:

## 1. **Image Captioning** 📸

- **Purpose**: Generate descriptions of images found in presentations and documents
- **Location**: `pptagent/multimodal.py`, `pptagent/document/element.py`
- **What it does**:
  - Analyzes images in slides and generates captions
  - Classifies images as: Table, Chart, Diagram, Banner, Background, Icon, Logo, or Picture
  - Helps the system understand what visual content is present

## 2. **Slide Layout Analysis** 🎨

- **Purpose**: Understand the visual structure and layout of presentation slides
- **Location**: `pptagent/induct.py`
- **What it does**:
  - Analyzes slide images to categorize them by layout type
  - Identifies functional slides (opening, TOC, section outlines, ending)
  - Groups similar slides together based on visual similarity
  - Extracts layout patterns from reference presentations

## 3. **Presentation Evaluation** ⚖️

- **Purpose**: Evaluate the visual design and style quality of generated presentations
- **Location**: `pptagent/ppteval.py`
- **What it does**:
  - Analyzes slide images to describe visual style
  - Evaluates content presentation and visual appeal
  - Provides feedback on design consistency

## 4. **Document Image Processing** 📄

- **Purpose**: Process images found in source documents (PDFs)
- **Location**: `pptagent/document/element.py`
- **What it does**:
  - Captions images extracted from PDF documents
  - Helps integrate visual content from source materials into presentations

## Why Separate Vision Models?

While some models (like GPT-4o) can handle both text and vision, using a dedicated vision model can:

- **Better performance**: Specialized vision models may be more accurate for image analysis
- **Cost optimization**: Some vision models are cheaper for image tasks
- **Flexibility**: You can use different models optimized for different tasks

## Recommended Vision Models for OpenRouter

- **`openai/gpt-4o`** - GPT-4 Omni with excellent vision capabilities (recommended)
- **`anthropic/claude-3-opus`** - Claude 3 Opus with strong vision understanding
- **`google/gemini-pro-vision`** - Google's vision model

You can set a custom vision model in your `.env` file:

```bash
VISION_MODEL=openai/gpt-4o
```
