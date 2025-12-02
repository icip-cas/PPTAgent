#!/usr/bin/env python3
"""
Test script to generate a presentation using PPTAgent.

This script demonstrates how to:
1. Load a pre-processed document
2. Load a template and slide induction
3. Generate a presentation

Usage:
    python generate_presentation.py

    To run with debug messages (detailed logging):
    LOG_LEVEL=DEBUG python generate_presentation.py

Environment variables needed (can be set in .env file):
    - OPEN_ROUTER_API_KEY: Your OpenRouter API key (recommended, supports many models)
      OR
    - OPENAI_API_KEY: Your OpenAI API key (fallback)
    - API_BASE (optional): API base URL (defaults to OpenRouter if OPEN_ROUTER_API_KEY is set, otherwise OpenAI)
    - LANGUAGE_MODEL (optional): Language model name (defaults to "gpt-4.1")
      For OpenRouter, use format like "openai/gpt-4" or "anthropic/claude-3-opus"
    - VISION_MODEL (optional): Vision model name (defaults to "gpt-4.1")
      For OpenRouter, use format like "openai/gpt-4-vision-preview"
    - LOG_LEVEL (optional): Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO
      Set to DEBUG to see detailed progress messages during generation
    - MAX_TOKENS (optional): Maximum tokens per API request (default: 16384)
"""

import asyncio
import json
import os
from glob import glob
from os.path import join

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pptagent.document import Document
from pptagent.induct import SlideInducter
from pptagent.multimodal import ImageLabler
from pptagent.pptgen import PPTAgent
from pptagent.presentation import Presentation
from pptagent.model_utils import ModelManager, parse_pdf
from pptagent.utils import Config, get_logger, ppt_to_images_async

# Set up logging
logger = get_logger(__name__)


# Number of slides to generate in the final presentation
NUM_SLIDES = 7


async def main():
    """Generate a test presentation."""
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.info("🚀 Starting PPTAgent test presentation generation...")
    logger.debug(f"Log level: {log_level}")
    logger.debug(f"Working directory: {os.getcwd()}")
    
    # Check for required environment variables
    openrouter_key = os.environ.get("OPEN_ROUTER_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    
    if not openrouter_key and not openai_key:
        logger.error("⚠️  Warning: No API key found!")
        print("⚠️  Warning: No API key found!")
        print("   Please set either:")
        print("   - OPEN_ROUTER_API_KEY (recommended, supports many models)")
        print("   - OPENAI_API_KEY (fallback)")
        print("   You can set these in a .env file in the project root.")
        print(f"   Current working directory: {os.getcwd()}")
        print(f"   .env file exists: {os.path.exists('.env')}")
        return
    elif openrouter_key:
        logger.info("✅ Using OpenRouter API")
        logger.debug(f"API key length: {len(openrouter_key)}")
        print("✅ Using OpenRouter API")
        print(f"   API key loaded: {openrouter_key[:20]}... (length: {len(openrouter_key)})")
    else:
        logger.info("✅ Using OpenAI API")
        logger.debug(f"API key length: {len(openai_key)}")
        print("✅ Using OpenAI API")
        print(f"   API key loaded: {openai_key[:20]}... (length: {len(openai_key)})")
    
    # Initialize models
    logger.info("📦 Initializing models...")
    print("\n📦 Initializing models...")
    models = ModelManager()
    logger.debug(f"Language model: {models.language_model.model}")
    logger.debug(f"Vision model: {models.vision_model.model}")
    
    # Test model connections
    logger.info("🔌 Testing model connections...")
    print("🔌 Testing model connections...")
    if not await models.test_connections():
        logger.error("❌ Model connection test failed!")
        print("❌ Model connection test failed!")
        print("   Please check your API configuration:")
        print("   - OPEN_ROUTER_API_KEY or OPENAI_API_KEY")
        print("   - API_BASE (if using custom endpoint)")
        print("   - LANGUAGE_MODEL (default: gpt-4.1)")
        print("   - VISION_MODEL (default: gpt-4.1)")
        print("   Note: For OpenRouter, model names should be in format like 'openai/gpt-4'")
        return
    logger.info("✅ Model connections successful!")
    print("✅ Model connections successful!")
    
    # Use pre-processed data from runs directory
    template_dir = join("runs", "t3n", "template")
    document_dir = join("runs", "t3n", "pdf")
    
    # Check if directories exist
    if not os.path.exists(template_dir):
        print(f"❌ Template directory not found: {template_dir}")
        print("   Please ensure you have pre-processed template data.")
        return
    
    if not os.path.exists(document_dir):
        print(f"❌ Document directory not found: {document_dir}")
        print("   Please ensure you have pre-processed document data.")
        return
    
    logger.info(f"📄 Loading template from: {template_dir}")
    print(f"\n📄 Loading template from: {template_dir}")
    config = Config(template_dir)
    logger.debug(f"Config run directory: {config.RUN_DIR}")
    
    # Load presentation template
    template_path = join(template_dir, "source.pptx")
    if not os.path.exists(template_path):
        logger.error(f"❌ Template file not found: {template_path}")
        print(f"❌ Template file not found: {template_path}")
        return
    
    logger.debug(f"Parsing template: {template_path}")
    presentation = Presentation.from_file(template_path, config)
    logger.info(f"✅ Loaded presentation template with {len(presentation.slides)} slides")
    logger.debug(f"Template has {len(presentation.error_history)} parsing errors")
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
        logger.info("🖼  Generating slide images from template (requires LibreOffice/soffice)...")
        print("🖼  Generating slide images from template (requires LibreOffice/soffice)...")
        logger.debug(f"Converting PPTX to images: {template_path} -> {slide_images_dir}")
        await ppt_to_images_async(template_path, slide_images_dir)
        logger.debug(f"Generated {len(glob(join(slide_images_dir, '*.jpg')))} slide images")

    # Align slide images with successfully parsed slides (skip error slides)
    ppt_images = sorted(
        f for f in os.listdir(slide_images_dir) if f.startswith("slide_") and f.endswith(".jpg")
    )
    logger.debug(f"Found {len(ppt_images)} slide images in directory")
    # Images may include ones for slides that failed to parse (recorded in error_history)
    expected_with_errors = len(presentation.slides) + len(presentation.error_history)
    if len(ppt_images) == expected_with_errors and presentation.error_history:
        logger.debug(f"Removing images for {len(presentation.error_history)} error slides")
        # Remove images for error slides
        for err_idx, _ in presentation.error_history:
            img_path = join(slide_images_dir, f"slide_{err_idx:04d}.jpg")
            if os.path.exists(img_path):
                logger.debug(f"Removing image for error slide {err_idx}: {img_path}")
                os.remove(img_path)
        # Re-number remaining images to be contiguous 1..N following slide.slide_idx
        for i, slide in enumerate(presentation.slides, 1):
            slide.slide_idx = i
            old_path = join(slide_images_dir, f"slide_{slide.real_idx:04d}.jpg")
            new_path = join(slide_images_dir, f"slide_{slide.slide_idx:04d}.jpg")
            if os.path.exists(old_path) and old_path != new_path:
                logger.debug(f"Renaming slide image: {old_path} -> {new_path}")
                os.rename(old_path, new_path)

    # 2) Render layout-only template images (if missing)
    if not os.path.exists(template_images_dir) or len(glob(join(template_images_dir, "*"))) == 0:
        logger.info("🧩 Generating layout-only template images...")
        print("🧩 Generating layout-only template images...")
        layout_only_path = join(template_dir, "template.pptx")
        # Save a layout-only version of the template
        logger.debug(f"Saving layout-only template: {layout_only_path}")
        presentation.save(layout_only_path, layout_only=True)
        logger.debug(f"Converting layout-only PPTX to images: {layout_only_path} -> {template_images_dir}")
        await ppt_to_images_async(layout_only_path, template_images_dir)
        logger.debug(f"Generated {len(glob(join(template_images_dir, '*.jpg')))} template images")

    # 3) Image statistics (captions, usage) for the template
    if os.path.exists(image_stats_path):
        logger.info("✅ Loaded existing image statistics for template")
        print("✅ Loaded existing image statistics for template")
        with open(image_stats_path, "r", encoding="utf-8") as f:
            image_stats = json.load(f)
        logger.debug(f"Loaded {len(image_stats)} image statistics")
        labeler = ImageLabler(presentation, config)
        labeler.apply_stats(image_stats)
    else:
        logger.info("🧠 Captioning template images to build image_stats.json (vision model)...")
        print("🧠 Captioning template images to build image_stats.json (vision model)...")
        labeler = ImageLabler(presentation, config)
        logger.debug(f"Captioning images using vision model: {models.vision_model.model}")
        # Use the global models.vision_model for captioning
        await labeler.caption_images_async(models.vision_model)
        logger.debug(f"Generated captions for {len(labeler.image_stats)} images")
        with open(image_stats_path, "w", encoding="utf-8") as f:
            json.dump(labeler.image_stats, f, ensure_ascii=False, indent=4)
        logger.info("✅ Generated image_stats.json for template")
        print("✅ Generated image_stats.json for template")

    # 4) Slide induction (layout + content schema) for the template
    if os.path.exists(slide_induction_path):
        logger.info("✅ Loaded existing slide_induction.json for template")
        print("✅ Loaded existing slide_induction.json for template")
        with open(slide_induction_path, "r", encoding="utf-8") as f:
            slide_induction = json.load(f)
        logger.debug(f"Loaded slide induction with {len(slide_induction.get('layouts', {}))} layouts")
    else:
        logger.info("🧱 Running slide induction on template to build slide_induction.json...")
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
        logger.debug("Step 1/2: Running layout induction (clustering slides by layout)...")
        layout_induction = await inducter.layout_induct()
        logger.debug(f"Layout induction found {len(layout_induction.get('layouts', {}))} unique layouts")
        logger.debug("Step 2/2: Running content induction (extracting content schemas)...")
        slide_induction = await inducter.content_induct(layout_induction)
        logger.debug(f"Content induction completed for {len(slide_induction.get('layouts', {}))} layouts")
        with open(slide_induction_path, "w", encoding="utf-8") as f:
            json.dump(slide_induction, f, ensure_ascii=False, indent=4)
        logger.info("✅ Generated slide_induction.json for template")
        print("✅ Generated slide_induction.json for template")
    
    # ------------------------------
    # Ensure refined document exists
    # ------------------------------
    logger.info(f"📚 Loading document from: {document_dir}")
    print(f"\n📚 Loading document from: {document_dir}")
    document_json_path = join(document_dir, "refined_doc.json")
    source_md_path = join(document_dir, "source.md")

    if os.path.exists(document_json_path):
        # Fast path: load pre-refined document
        logger.debug(f"Loading refined document from: {document_json_path}")
        with open(document_json_path, "r", encoding="utf-8") as f:
            document_data = json.load(f)
        document = Document(**document_data)
        logger.info(f"✅ Loaded existing refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        logger.debug(f"Document has {len(document.sections)} sections")
        print(f"✅ Loaded existing refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        print(f"   Sections: {len(document.sections)}")
    else:
        print("🧾 No refined_doc.json found. Attempting to build it from PDF/Markdown...")

        # 1) Get markdown content (source.md) – either existing, or via MinerU (parse_pdf)
        if os.path.exists(source_md_path):
            logger.info("📖 Using existing source.md as document markdown...")
            print("📖 Using existing source.md as document markdown...")
            with open(source_md_path, "r", encoding="utf-8") as f:
                text_content = f.read()
            logger.debug(f"Loaded markdown content: {len(text_content)} characters")
        else:
            pdf_path = join(document_dir, "source.pdf")
            if not os.path.exists(pdf_path):
                logger.error(f"❌ Neither refined_doc.json nor source.md nor source.pdf found in {document_dir}")
                print(f"❌ Neither refined_doc.json nor source.md nor source.pdf found in {document_dir}")
                print("   Please provide at least a PDF (source.pdf) or markdown (source.md).")
                return

            # Require MinerU API for PDF parsing
            if not os.environ.get("MINERU_API"):
                logger.error("❌ MINERU_API is not set, cannot parse PDF to markdown.")
                print("❌ MINERU_API is not set, cannot parse PDF to markdown.")
                print("   To enable automatic PDF parsing, install and run MinerU, then set:")
                print('   MINERU_API="http://localhost:8000/file_parse"')
                print("   Alternatively, create source.md manually in runs/pru/pdf/.")
                return

            logger.info("🧮 Parsing PDF to markdown via MinerU (this may take a while)...")
            print("🧮 Parsing PDF to markdown via MinerU (this may take a while)...")
            logger.debug(f"Parsing PDF: {pdf_path}")
            try:
                await parse_pdf(pdf_path, document_dir)
                logger.debug("PDF parsing completed")
            except Exception as e:
                logger.error(f"❌ PDF parsing via MinerU failed: {e}", exc_info=True)
                print(f"❌ PDF parsing via MinerU failed: {e}")
                import traceback

                traceback.print_exc()
                return

            if not os.path.exists(source_md_path):
                logger.error("❌ Expected source.md after PDF parsing, but it was not found.")
                print("❌ Expected source.md after PDF parsing, but it was not found.")
                print("   Please check your MinerU setup or create source.md manually.")
                return

            with open(source_md_path, "r", encoding="utf-8") as f:
                text_content = f.read()
            logger.debug(f"Loaded markdown content from PDF: {len(text_content)} characters")

        # 2) Refine markdown into structured Document and cache to refined_doc.json
        logger.info("🧠 Refining markdown into structured document (refined_doc.json)...")
        print("🧠 Refining markdown into structured document (refined_doc.json)...")
        logger.debug(f"Using language model: {models.language_model.model}")
        logger.debug(f"Using vision model: {models.vision_model.model}")
        try:
            refined_doc = await Document.from_markdown(
                text_content,
                models.language_model,
                models.vision_model,
                document_dir,
            )
            logger.debug(f"Document refinement completed: {len(refined_doc.sections)} sections")
        except Exception as e:
            logger.error(f"❌ Document.from_markdown failed: {e}", exc_info=True)
            print(f"❌ Document.from_markdown failed: {e}")
            import traceback

            traceback.print_exc()
            return

        with open(document_json_path, "w", encoding="utf-8") as f:
            json.dump(refined_doc.model_dump(), f, ensure_ascii=False, indent=4)
        logger.debug(f"Saved refined document to: {document_json_path}")

        document = refined_doc
        logger.info(f"✅ Generated refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        print(f"✅ Generated refined_doc.json: {document.metadata.get('title', 'Untitled')}")
        print(f"   Sections: {len(document.sections)}")
    
    # Initialize PPTAgent
    logger.info("🤖 Initializing PPTAgent...")
    print("\n🤖 Initializing PPTAgent...")
    ppt_agent = PPTAgent(
        language_model=models.language_model,
        vision_model=models.vision_model,
        error_exit=False,  # Don't exit on errors, continue with warnings
        retry_times=3,     # Retry failed operations 3 times
    )
    logger.debug(f"PPTAgent initialized with retry_times={ppt_agent.retry_times}")
    
    # Set reference presentation and slide induction
    logger.debug("Setting reference presentation and slide induction...")
    ppt_agent.set_reference(
        slide_induction=slide_induction,
        presentation=presentation,
    )
    logger.info("✅ PPTAgent initialized with reference template")
    logger.debug(f"PPTAgent has {len(ppt_agent.layouts)} layouts available")
    print("✅ PPTAgent initialized with reference template")
    
    # Apply image statistics if available
    image_stats_path = join(template_dir, "image_stats.json")
    if os.path.exists(image_stats_path):
        logger.info("📊 Applying image statistics...")
        print("📊 Applying image statistics...")
        labeler = ImageLabler(ppt_agent.presentation, config)
        with open(image_stats_path, "r", encoding="utf-8") as f:
            image_stats = json.load(f)
        labeler.apply_stats(image_stats)
        logger.debug(f"Applied statistics for {len(image_stats)} images")
        logger.info("✅ Image statistics applied")
        print("✅ Image statistics applied")
    
    # Generate presentation
    logger.info("🎨 Generating presentation...")
    logger.info(f"Target number of slides: {NUM_SLIDES}")
    print("\n🎨 Generating presentation...")
    print(f"   This may take a few minutes depending on the number of slides (NUM_SLIDES={NUM_SLIDES})...")
    try:
        logger.debug("Step 1: Generating outline...")
        generated_presentation, history = await ppt_agent.generate_pres(
            source_doc=document,
            num_slides=NUM_SLIDES,
        )
        logger.debug(f"Generation completed. History has {len(history)} entries")

        # Save the generated presentation
        output_path = "test_output.pptx"
        logger.debug(f"Saving presentation to: {output_path}")
        generated_presentation.save(output_path)
        logger.info(f"✅ Successfully generated presentation!")
        logger.info(f"   Saved to: {output_path}")
        logger.info(f"   Number of slides: {len(generated_presentation.slides)}")
        print(f"\n✅ Successfully generated presentation!")
        print(f"   Saved to: {output_path}")
        print(f"   Number of slides: {len(generated_presentation.slides)}")

    except Exception as e:
        logger.error(f"❌ Error during presentation generation: {e}", exc_info=True)
        print(f"\n❌ Error during presentation generation: {e}")
        import traceback
        traceback.print_exc()
        return

    logger.info("🎉 Test completed successfully!")
    print("\n🎉 Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

