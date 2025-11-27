#!/usr/bin/env python3
"""
Test script to generate a presentation using PPTAgent.

This script demonstrates how to:
1. Load a pre-processed document
2. Load a template and slide induction
3. Generate a presentation

Usage:
    python test_generate_presentation.py

Environment variables needed (can be set in .env file):
    - OPEN_ROUTER_API_KEY: Your OpenRouter API key (recommended, supports many models)
      OR
    - OPENAI_API_KEY: Your OpenAI API key (fallback)
    - API_BASE (optional): API base URL (defaults to OpenRouter if OPEN_ROUTER_API_KEY is set, otherwise OpenAI)
    - LANGUAGE_MODEL (optional): Language model name (defaults to "gpt-4.1")
      For OpenRouter, use format like "openai/gpt-4" or "anthropic/claude-3-opus"
    - VISION_MODEL (optional): Vision model name (defaults to "gpt-4.1")
      For OpenRouter, use format like "openai/gpt-4-vision-preview"
"""

import asyncio
import json
import os
from glob import glob
from os.path import join

from pptagent.document import Document
from pptagent.induct import SlideInducter
from pptagent.multimodal import ImageLabler
from pptagent.pptgen import PPTAgent
from pptagent.presentation import Presentation
from pptagent.model_utils import ModelManager, parse_pdf
from pptagent.utils import Config, ppt_to_images_async


# Number of slides to generate in the final presentation
NUM_SLIDES = 1


async def main():
    """Generate a test presentation."""
    print("🚀 Starting PPTAgent test presentation generation...")
    
    # Check for required environment variables
    if not os.environ.get("OPEN_ROUTER_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  Warning: No API key found!")
        print("   Please set either:")
        print("   - OPEN_ROUTER_API_KEY (recommended, supports many models)")
        print("   - OPENAI_API_KEY (fallback)")
        print("   You can set these in a .env file in the project root.")
    elif os.environ.get("OPEN_ROUTER_API_KEY"):
        print("✅ Using OpenRouter API")
    else:
        print("✅ Using OpenAI API")
    
    # Initialize models
    print("\n📦 Initializing models...")
    models = ModelManager()
    
    # Test model connections
    print("🔌 Testing model connections...")
    if not await models.test_connections():
        print("❌ Model connection test failed!")
        print("   Please check your API configuration:")
        print("   - OPEN_ROUTER_API_KEY or OPENAI_API_KEY")
        print("   - API_BASE (if using custom endpoint)")
        print("   - LANGUAGE_MODEL (default: gpt-4.1)")
        print("   - VISION_MODEL (default: gpt-4.1)")
        print("   Note: For OpenRouter, model names should be in format like 'openai/gpt-4'")
        return
    print("✅ Model connections successful!")
    
    # Use pre-processed data from runs directory
    template_dir = join("runs", "pru", "template")
    document_dir = join("runs", "pru", "pdf")
    
    # Check if directories exist
    if not os.path.exists(template_dir):
        print(f"❌ Template directory not found: {template_dir}")
        print("   Please ensure you have pre-processed template data.")
        return
    
    if not os.path.exists(document_dir):
        print(f"❌ Document directory not found: {document_dir}")
        print("   Please ensure you have pre-processed document data.")
        return
    
    print(f"\n📄 Loading template from: {template_dir}")
    config = Config(template_dir)
    
    # Load presentation template
    template_path = join(template_dir, "source.pptx")
    if not os.path.exists(template_path):
        print(f"❌ Template file not found: {template_path}")
        return
    
    presentation = Presentation.from_file(template_path, config)
    print(f"✅ Loaded presentation template with {len(presentation.slides)} slides")

    # ------------------------------------------------------------------
    # Ensure template analysis artifacts exist (images, stats, induction)
    # This mirrors the logic in scripts/template_induct.py and backend.py
    # ------------------------------------------------------------------
    slide_images_dir = join(template_dir, "slide_images")
    template_images_dir = join(template_dir, "template_images")
    image_stats_path = join(template_dir, "image_stats.json")
    slide_induction_path = join(template_dir, "slide_induction.json")

    # 1) Render slide images from source.pptx (if missing)
    if not os.path.exists(slide_images_dir) or len(glob(join(slide_images_dir, "*"))) == 0:
        print("🖼  Generating slide images from template (requires LibreOffice/soffice)...")
        await ppt_to_images_async(template_path, slide_images_dir)

    # Align slide images with successfully parsed slides (skip error slides)
    ppt_images = sorted(
        f for f in os.listdir(slide_images_dir) if f.startswith("slide_") and f.endswith(".jpg")
    )
    # Images may include ones for slides that failed to parse (recorded in error_history)
    expected_with_errors = len(presentation.slides) + len(presentation.error_history)
    if len(ppt_images) == expected_with_errors and presentation.error_history:
        # Remove images for error slides
        for err_idx, _ in presentation.error_history:
            img_path = join(slide_images_dir, f"slide_{err_idx:04d}.jpg")
            if os.path.exists(img_path):
                os.remove(img_path)
        # Re-number remaining images to be contiguous 1..N following slide.slide_idx
        for i, slide in enumerate(presentation.slides, 1):
            slide.slide_idx = i
            old_path = join(slide_images_dir, f"slide_{slide.real_idx:04d}.jpg")
            new_path = join(slide_images_dir, f"slide_{slide.slide_idx:04d}.jpg")
            if os.path.exists(old_path) and old_path != new_path:
                os.rename(old_path, new_path)

    # 2) Render layout-only template images (if missing)
    if not os.path.exists(template_images_dir) or len(glob(join(template_images_dir, "*"))) == 0:
        print("🧩 Generating layout-only template images...")
        layout_only_path = join(template_dir, "template.pptx")
        # Save a layout-only version of the template
        presentation.save(layout_only_path, layout_only=True)
        await ppt_to_images_async(layout_only_path, template_images_dir)

    # 3) Image statistics (captions, usage) for the template
    if os.path.exists(image_stats_path):
        with open(image_stats_path, "r", encoding="utf-8") as f:
            image_stats = json.load(f)
        labeler = ImageLabler(presentation, config)
        labeler.apply_stats(image_stats)
        print("✅ Loaded existing image statistics for template")
    else:
        print("🧠 Captioning template images to build image_stats.json (vision model)...")
        labeler = ImageLabler(presentation, config)
        # Use the global models.vision_model for captioning
        await labeler.caption_images_async(models.vision_model)
        with open(image_stats_path, "w", encoding="utf-8") as f:
            json.dump(labeler.image_stats, f, ensure_ascii=False, indent=4)
        print("✅ Generated image_stats.json for template")

    # 4) Slide induction (layout + content schema) for the template
    if os.path.exists(slide_induction_path):
        with open(slide_induction_path, "r", encoding="utf-8") as f:
            slide_induction = json.load(f)
        print("✅ Loaded existing slide_induction.json for template")
    else:
        print("🧱 Running slide induction on template to build slide_induction.json...")
        inducter = SlideInducter(
            presentation,
            slide_images_dir,
            template_images_dir,
            config,
            models.image_model,
            models.language_model,
            models.vision_model,
        )
        layout_induction = await inducter.layout_induct()
        slide_induction = await inducter.content_induct(layout_induction)
        with open(slide_induction_path, "w", encoding="utf-8") as f:
            json.dump(slide_induction, f, ensure_ascii=False, indent=4)
        print("✅ Generated slide_induction.json for template")
    
    # ------------------------------
    # Ensure refined document exists
    # ------------------------------
    print(f"\n📚 Loading document from: {document_dir}")
    document_json_path = join(document_dir, "refined_doc.json")
    source_md_path = join(document_dir, "source.md")

    if os.path.exists(document_json_path):
        # Fast path: load pre-refined document
        with open(document_json_path, "r", encoding="utf-8") as f:
            document_data = json.load(f)
        document = Document(**document_data)
        print(f"✅ Loaded existing refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        print(f"   Sections: {len(document.sections)}")
    else:
        print("🧾 No refined_doc.json found. Attempting to build it from PDF/Markdown...")

        # 1) Get markdown content (source.md) – either existing, or via MinerU (parse_pdf)
        if os.path.exists(source_md_path):
            print("📖 Using existing source.md as document markdown...")
            with open(source_md_path, "r", encoding="utf-8") as f:
                text_content = f.read()
        else:
            pdf_path = join(document_dir, "source.pdf")
            if not os.path.exists(pdf_path):
                print(f"❌ Neither refined_doc.json nor source.md nor source.pdf found in {document_dir}")
                print("   Please provide at least a PDF (source.pdf) or markdown (source.md).")
                return

            # Require MinerU API for PDF parsing
            if not os.environ.get("MINERU_API"):
                print("❌ MINERU_API is not set, cannot parse PDF to markdown.")
                print("   To enable automatic PDF parsing, install and run MinerU, then set:")
                print('   MINERU_API="http://localhost:8000/file_parse"')
                print("   Alternatively, create source.md manually in runs/pru/pdf/.")
                return

            print("🧮 Parsing PDF to markdown via MinerU (this may take a while)...")
            try:
                await parse_pdf(pdf_path, document_dir)
            except Exception as e:
                print(f"❌ PDF parsing via MinerU failed: {e}")
                import traceback

                traceback.print_exc()
                return

            if not os.path.exists(source_md_path):
                print("❌ Expected source.md after PDF parsing, but it was not found.")
                print("   Please check your MinerU setup or create source.md manually.")
                return

            with open(source_md_path, "r", encoding="utf-8") as f:
                text_content = f.read()

        # 2) Refine markdown into structured Document and cache to refined_doc.json
        print("🧠 Refining markdown into structured document (refined_doc.json)...")
        try:
            refined_doc = await Document.from_markdown(
                text_content,
                models.language_model,
                models.vision_model,
                document_dir,
            )
        except Exception as e:
            print(f"❌ Document.from_markdown failed: {e}")
            import traceback

            traceback.print_exc()
            return

        with open(document_json_path, "w", encoding="utf-8") as f:
            json.dump(refined_doc.model_dump(), f, ensure_ascii=False, indent=4)

        document = refined_doc
        print(f"✅ Generated refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        print(f"   Sections: {len(document.sections)}")
    
    # Initialize PPTAgent
    print("\n🤖 Initializing PPTAgent...")
    ppt_agent = PPTAgent(
        language_model=models.language_model,
        vision_model=models.vision_model,
        error_exit=False,  # Don't exit on errors, continue with warnings
        retry_times=3,     # Retry failed operations 3 times
    )
    
    # Set reference presentation and slide induction
    ppt_agent.set_reference(
        slide_induction=slide_induction,
        presentation=presentation,
    )
    print("✅ PPTAgent initialized with reference template")
    
    # Apply image statistics if available
    image_stats_path = join(template_dir, "image_stats.json")
    if os.path.exists(image_stats_path):
        print("📊 Applying image statistics...")
        labeler = ImageLabler(ppt_agent.presentation, config)
        with open(image_stats_path, "r", encoding="utf-8") as f:
            image_stats = json.load(f)
        labeler.apply_stats(image_stats)
        print("✅ Image statistics applied")
    
    # Generate presentation
    print("\n🎨 Generating presentation...")
    print(f"   This may take a few minutes depending on the number of slides (NUM_SLIDES={NUM_SLIDES})...")
    try:
        generated_presentation, _ = await ppt_agent.generate_pres(
            source_doc=document,
            num_slides=NUM_SLIDES,
        )

        # Save the generated presentation
        output_path = "test_output.pptx"
        generated_presentation.save(output_path)
        print(f"\n✅ Successfully generated presentation!")
        print(f"   Saved to: {output_path}")
        print(f"   Number of slides: {len(generated_presentation.slides)}")

    except Exception as e:
        print(f"\n❌ Error during presentation generation: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n🎉 Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

