import asyncio
import os
from collections import defaultdict

from jinja2 import Template

from pptagent.llms import LLM, AsyncLLM
from pptagent.model_utils import (
    get_cluster,
    get_image_embedding,
    images_cosine_similarity,
)
from pptagent.presentation import Presentation
from pptagent.utils import Config, get_logger, package_join, pjoin, tenacity

logger = get_logger(__name__)


class SlideInducter:
    """
    Stage I: Presentation Analysis.
    This stage is to analyze the presentation: cluster slides into different layouts, and extract content schema for each layout.
    """

    def __init__(
        self,
        prs: Presentation,
        ppt_image_folder: str,
        template_image_folder: str,
        config: Config,
        image_models: list,
        language_model: LLM,
        vision_model: LLM,
        use_assert: bool = True,
    ):
        """
        Initialize the SlideInducter.

        Args:
            prs (Presentation): The presentation object.
            ppt_image_folder (str): The folder containing PPT images.
            template_image_folder (str): The folder containing normalized slide images.
            config (Config): The configuration object.
            image_models (list): A list of image models.
        """
        self.prs = prs
        self.config = config
        self.ppt_image_folder = ppt_image_folder
        self.template_image_folder = template_image_folder
        self.language_model = language_model
        self.vision_model = vision_model
        self.image_models = image_models
        if not use_assert:
            return
        assert (
            len(os.listdir(template_image_folder))
            == len(prs.slides)
            == len(os.listdir(ppt_image_folder))
        ), "The number of slides in the template image folder and the presentation image folder must be the same as the number of slides in the presentation"

    def layout_induct(self):
        """
        Perform layout induction for the presentation.
        """
        layout_induction = defaultdict(lambda: defaultdict(list))
        content_slides_index, functional_cluster = self.category_split()
        for layout_name, cluster in functional_cluster.items():
            for slide_idx in cluster:
                content_type = self.prs.slides[slide_idx - 1].get_content_type()
                layout_key = layout_name + ":" + content_type
                if "slides" not in layout_induction[layout_key]:
                    layout_induction[layout_key]["slides"] = []
                layout_induction[layout_key]["slides"].append(slide_idx)
        for layout_name, cluster in layout_induction.items():
            if "slides" in cluster and cluster["slides"]:
                cluster["template_id"] = cluster["slides"][-1]

        functional_keys = list(layout_induction.keys())
        function_slides_index = set()
        for layout_name, cluster in layout_induction.items():
            function_slides_index.update(cluster["slides"])
        used_slides_index = function_slides_index.union(content_slides_index)
        for i in range(len(self.prs.slides)):
            if i + 1 not in used_slides_index:
                content_slides_index.add(i + 1)
        self.layout_split(content_slides_index, layout_induction)
        layout_induction["functional_keys"] = functional_keys
        return layout_induction

    def category_split(self):
        """
        Split slides into categories based on their functional purpose.
        """
        category_split_template = Template(
            open(package_join("prompts", "category_split.txt")).read()
        )
        functional_cluster = self.language_model(
            category_split_template.render(slides=self.prs.to_text()),
            return_json=True,
        )
        functional_slides = set(sum(functional_cluster.values(), []))
        content_slides_index = set(range(1, len(self.prs) + 1)) - functional_slides

        return content_slides_index, functional_cluster

    def layout_split(self, content_slides_index: set[int], layout_induction: dict):
        """
        Cluster slides into different layouts.
        """
        embeddings = get_image_embedding(self.template_image_folder, *self.image_models)
        assert len(embeddings) == len(self.prs)
        template = Template(open(package_join("prompts", "ask_category.txt")).read())
        content_split = defaultdict(list)
        for slide_idx in content_slides_index:
            slide = self.prs.slides[slide_idx - 1]
            content_type = slide.get_content_type()
            layout_name = slide.slide_layout_name
            content_split[(layout_name, content_type)].append(slide_idx)

        for (layout_name, content_type), slides in content_split.items():
            sub_embeddings = [
                embeddings[f"slide_{slide_idx:04d}.jpg"] for slide_idx in slides
            ]
            similarity = images_cosine_similarity(sub_embeddings)
            for cluster in get_cluster(similarity):
                slide_indexs = [slides[i] for i in cluster]
                template_id = max(
                    slide_indexs,
                    key=lambda x: len(self.prs.slides[x - 1].shapes),
                )
                cluster_name = (
                    self.vision_model(
                        template.render(
                            existed_layoutnames=list(layout_induction.keys()),
                        ),
                        pjoin(self.ppt_image_folder, f"slide_{template_id:04d}.jpg"),
                    )
                    + ":"
                    + content_type
                )
                layout_induction[cluster_name]["template_id"] = template_id
                layout_induction[cluster_name]["slides"] = slide_indexs

    @tenacity
    def content_induct(self):
        """
        Perform content schema extraction for the presentation.
        """
        layout_induction = self.layout_induct()
        content_induct_prompt = Template(
            open(package_join("prompts", "content_induct.txt")).read()
        )
        for layout_name, cluster in layout_induction.items():
            if "template_id" in cluster and "content_schema" not in cluster:
                schema = self.language_model(
                    content_induct_prompt.render(
                        slide=self.prs.slides[cluster["template_id"] - 1].to_html(
                            element_id=False, paragraph_id=False
                        )
                    ),
                    return_json=True,
                )
                for k in list(schema.keys()):
                    if "data" not in schema[k]:
                        raise ValueError(f"Cannot find `data` in {k}\n{schema[k]}")
                    if len(schema[k]["data"]) == 0:
                        logger.warning("Empty content schema: %s", schema[k])
                        schema.pop(k)
                assert len(schema) > 0, "No content schema generated"
                layout_induction[layout_name]["content_schema"] = schema
        return layout_induction


class SlideInducterAsync(SlideInducter):
    def __init__(
        self,
        prs: Presentation,
        ppt_image_folder: str,
        template_image_folder: str,
        config: Config,
        image_models: list,
        language_model: AsyncLLM,
        vision_model: AsyncLLM,
    ):
        """
        Initialize the SlideInducterAsync with async models.

        Args:
            prs (Presentation): The presentation object.
            ppt_image_folder (str): The folder containing PPT images.
            template_image_folder (str): The folder containing normalized slide images.
            config (Config): The configuration object.
            image_models (list): A list of image models.
            language_model (AsyncLLM): The async language model.
            vision_model (AsyncLLM): The async vision model.
        """
        super().__init__(
            prs,
            ppt_image_folder,
            template_image_folder,
            config,
            image_models,
            language_model,
            vision_model,
        )

    async def category_split(self):
        """
        Async version: Split slides into categories based on their functional purpose.
        """
        category_split_template = Template(
            open(package_join("prompts", "category_split.txt")).read()
        )
        functional_cluster = await self.language_model(
            category_split_template.render(slides=self.prs.to_text()),
            return_json=True,
        )
        functional_slides = set(sum(functional_cluster.values(), []))
        content_slides_index = set(range(1, len(self.prs) + 1)) - functional_slides

        return content_slides_index, functional_cluster

    async def layout_split(
        self, content_slides_index: set[int], layout_induction: dict
    ):
        """
        Async version: Cluster slides into different layouts.
        """
        embeddings = get_image_embedding(self.template_image_folder, *self.image_models)
        assert len(embeddings) == len(self.prs)
        template = Template(open(package_join("prompts", "ask_category.txt")).read())
        content_split = defaultdict(list)
        for slide_idx in content_slides_index:
            slide = self.prs.slides[slide_idx - 1]
            content_type = slide.get_content_type()
            layout_name = slide.slide_layout_name
            content_split[(layout_name, content_type)].append(slide_idx)

        vision_tasks = []
        cluster_info = []
        for (layout_name, content_type), slides in content_split.items():
            sub_embeddings = [
                embeddings[f"slide_{slide_idx:04d}.jpg"] for slide_idx in slides
            ]
            similarity = images_cosine_similarity(sub_embeddings)
            for cluster in get_cluster(similarity):
                slide_indexs = [slides[i] for i in cluster]
                template_id = max(
                    slide_indexs,
                    key=lambda x: len(self.prs.slides[x - 1].shapes),
                )

                vision_tasks.append(
                    self.vision_model(
                        template.render(
                            existed_layoutnames=list(layout_induction.keys()),
                        ),
                        pjoin(self.ppt_image_folder, f"slide_{template_id:04d}.jpg"),
                    )
                )
                cluster_info.append((template_id, slide_indexs, content_type))

        vision_results = await asyncio.gather(*vision_tasks)
        for (template_id, slide_indexs, content_type), cluster_name_prefix in zip(
            cluster_info, vision_results
        ):
            cluster_name = cluster_name_prefix + ":" + content_type
            layout_induction[cluster_name]["template_id"] = template_id
            layout_induction[cluster_name]["slides"] = slide_indexs

    async def layout_induct(self):
        """
        Async version: Perform layout induction for the presentation.
        """
        layout_induction = defaultdict(lambda: defaultdict(list))
        content_slides_index, functional_cluster = await self.category_split()
        for layout_name, cluster in functional_cluster.items():
            for slide_idx in cluster:
                content_type = self.prs.slides[slide_idx - 1].get_content_type()
                layout_key = layout_name + ":" + content_type
                if "slides" not in layout_induction[layout_key]:
                    layout_induction[layout_key]["slides"] = []
                layout_induction[layout_key]["slides"].append(slide_idx)
        for layout_name, cluster in layout_induction.items():
            if "slides" in cluster and cluster["slides"]:
                cluster["template_id"] = cluster["slides"][-1]

        functional_keys = list(layout_induction.keys())
        function_slides_index = set()
        for layout_name, cluster in layout_induction.items():
            function_slides_index.update(cluster["slides"])
        used_slides_index = function_slides_index.union(content_slides_index)
        for i in range(len(self.prs.slides)):
            if i + 1 not in used_slides_index:
                content_slides_index.add(i + 1)
        await self.layout_split(content_slides_index, layout_induction)
        layout_induction["functional_keys"] = functional_keys
        return layout_induction

    @tenacity
    async def content_induct(self, layout_induction: dict):
        """
        Async version: Perform content schema extraction for the presentation.
        """
        content_induct_prompt = Template(
            open(package_join("prompts", "content_induct.txt")).read()
        )

        tasks = {}
        for layout_name, cluster in layout_induction.items():
            if "template_id" in cluster and "content_schema" not in cluster:
                slide = self.prs.slides[cluster["template_id"] - 1].to_html(
                    element_id=False, paragraph_id=False
                )
                task = self.language_model(
                    content_induct_prompt.render(slide=slide), return_json=True
                )
                tasks[layout_name] = task

        if tasks:
            results = await asyncio.gather(*tasks.values())
            for layout_name, schema in zip(tasks.keys(), results):
                # Validate schema structure
                for key in list(schema.keys()):
                    if "data" not in schema[key]:
                        raise ValueError(f"Missing data field in {key}\n{schema[key]}")
                    if not schema[key]["data"]:
                        logger.warning("Removing empty schema: %s", key)
                        schema.pop(key)

                if not schema:
                    raise ValueError(f"Empty schema generated for layout {layout_name}")

                layout_induction[layout_name]["content_schema"] = schema
                logger.debug("Updated content schema for %s", layout_name)

        return layout_induction
