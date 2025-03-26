import json

from pptagent.llms import AsyncLLM
from pptagent.utils import Config, pjoin


# Common test configuration
class TestConfig:
    def __init__(self):
        self.template = "resource/test/test_template"
        self.document = "resource/test/test_pdf"
        self.ppt = "resource/test/test.pptx"
        self.api_base = "http://api.cipsup.cn/v1"

        # Models
        self.language_model = AsyncLLM("Qwen2.5-72B-Instruct-GPTQ-Int4", self.api_base)
        self.vision_model = AsyncLLM("Qwen2.5-VL-72B-Instruct-AWQ", self.api_base)
        self.text_embedder = AsyncLLM("bge-m3", self.api_base)

        # Configuration object
        self.config = Config(self.template)

    def get_slide_induction(self):
        """Load slide induction data"""
        return json.load(
            open(pjoin(self.template, "template_induct/backend/induct_cache.json"))
        )

    def get_document_json(self):
        """Load document JSON"""
        return json.load(open(f"{self.document}/refined_doc.json"))

    def get_outline(self):
        """Load outline data"""
        return json.load(open(f"{self.document}/outline.json"))


# Create a global instance
test_config = TestConfig()
