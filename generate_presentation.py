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
from os.path import join

from pptagent.document import Document
from pptagent.multimodal import ImageLabler
from pptagent.pptgen import PPTAgent
from pptagent.presentation import Presentation
from pptagent.model_utils import ModelManager
from pptagent.utils import Config


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
    template_dir = join("runs", "pptx", "default_template")
    document_dir = join("runs", "pdf", "57b32a38d68d1e62908a3d4fe77441c2")
    
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
    
    # Load slide induction
    slide_induction_path = join(template_dir, "slide_induction.json")
    if not os.path.exists(slide_induction_path):
        print(f"❌ Slide induction file not found: {slide_induction_path}")
        return
    
    with open(slide_induction_path, "r", encoding="utf-8") as f:
        slide_induction = json.load(f)
    print("✅ Loaded slide induction data")
    
    # Load document
    print(f"\n📚 Loading document from: {document_dir}")
    document_json_path = join(document_dir, "refined_doc.json")
    if not os.path.exists(document_json_path):
        print(f"❌ Document JSON not found: {document_json_path}")
        return
    
    with open(document_json_path, "r", encoding="utf-8") as f:
        document_data = json.load(f)
    
    document = Document(**document_data)
    print(f"✅ Loaded document: {document.metadata.get('title', 'Untitled')}")
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
    print("   This may take a few minutes depending on the number of slides...")
    
    num_slides = 5  # Generate 5 slides for testing
    try:
        generated_presentation, _ = await ppt_agent.generate_pres(
            source_doc=document,
            num_slides=num_slides,
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

