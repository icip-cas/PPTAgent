import json

from pptagent.llms import AsyncLLM
from pptagent.utils import Config, package_join, pjoin


# Common test configuration
class TestConfig:
    def __init__(self):
        self.template = package_join("runs", "pptx", "default_template")
        self.document = package_join("runs", "pdf", "57b32a38d68d1e62908a3d4fe77441c2")
        self.ppt = package_join("test", "test.pptx")
        self.api_base = "http://api.cipsup.cn/v1"

        # Models
        self.language_model = AsyncLLM("Qwen2.5-72B-Instruct-GPTQ-Int4", self.api_base)
        self.vision_model = AsyncLLM("Qwen2.5-VL-72B-Instruct-AWQ", self.api_base)
        self.text_embedder = AsyncLLM("bge-m3", self.api_base)

        # Configuration object
        self.config = Config(self.template)

    def get_slide_induction(self):
        """Load slide induction data"""
        return json.load(open(pjoin(self.template, "slide_induction.json")))

    def get_document_json(self):
        """Load document JSON"""
        return json.load(open(pjoin(self.document, "refined_doc.json")))

    def get_outline(self):
        """Load outline data"""
        return json.load(open(pjoin(self.document, "outline.json")))

    def get_image_stats(self):
        """Load captions data"""
        return json.load(open(pjoin(self.template, "image_stats.json")))


# Create a global instance
test_config = TestConfig()
