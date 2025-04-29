import asyncio
from typing import Optional

import PIL.Image

from pptagent.llms import LLM, AsyncLLM
from pptagent.presentation import Picture, Presentation
from pptagent.utils import Config, get_logger, package_join, pbasename, pjoin

logger = get_logger(__name__)


class ImageLabler:
    """
    A class to extract images information, including caption, size, and appearance times in a presentation.
    """

    def __init__(self, presentation: Presentation, config: Config):
        """
        Initialize the ImageLabler.

        Args:
            presentation (Presentation): The presentation object.
            config (Config): The configuration object.
        """
        self.presentation = presentation
        self.slide_area = presentation.slide_width.pt * presentation.slide_height.pt
        self.image_stats = {}
        self.config = config
        self.collect_images()

    def apply_stats(self, image_stats: Optional[dict[str, dict]] = None):
        """
        Apply image captions to the presentation.
        """
        if image_stats is None:
            image_stats = self.image_stats

        for slide in self.presentation.slides:
            for shape in slide.shape_filter(Picture):
                if shape.caption is None:
                    caption = image_stats[pbasename(shape.img_path)]["caption"]
                    shape.caption = max(caption.split("\n"), key=len)

    async def caption_images_async(self, vision_model: AsyncLLM):
        """
        Generate captions for images in the presentation asynchronously.

        Args:
            vision_model (AsyncLLM): The async vision model to use for captioning.

        Returns:
            dict: Dictionary containing image stats with captions.
        """
        assert isinstance(
            vision_model, AsyncLLM
        ), "vision_model must be an AsyncLLM instance"
        caption_prompt = open(package_join("prompts", "caption.txt")).read()

        async with asyncio.TaskGroup() as tg:
            for image, stats in self.image_stats.items():
                if "caption" not in stats:
                    task = tg.create_task(
                        vision_model(
                            caption_prompt,
                            pjoin(self.config.IMAGE_DIR, image),
                        )
                    )
                    task.add_done_callback(
                        lambda t, image=image: (
                            self.image_stats[image].update({"caption": t.result()}),
                            logger.debug("captioned %s: %s", image, t.result()),
                        )
                    )

        self.apply_stats()
        return self.image_stats

    def caption_images(self, vision_model: LLM):
        """
        Generate captions for images in the presentation.

        Args:
            vision_model (LLM): The vision model to use for captioning.

        Returns:
            dict: Dictionary containing image stats with captions.
        """
        assert isinstance(vision_model, LLM), "vision_model must be an LLM instance"
        caption_prompt = open(package_join("prompts", "caption.txt")).read()
        for image, stats in self.image_stats.items():
            if "caption" not in stats:
                stats["caption"] = vision_model(
                    caption_prompt, pjoin(self.config.IMAGE_DIR, image)
                )
                logger.debug("captioned %s: %s", image, stats["caption"])
        self.apply_stats()
        return self.image_stats

    def collect_images(self):
        """
        Collect images from the presentation and gather other information.
        """
        for slide_index, slide in enumerate(self.presentation.slides):
            for shape in slide.shape_filter(Picture):
                image_path = pbasename(shape.img_path)
                if image_path == "pic_placeholder.png":
                    continue
                if image_path not in self.image_stats:
                    size = PIL.Image.open(pjoin(self.config.IMAGE_DIR, image_path)).size
                    self.image_stats[image_path] = {
                        "size": size,
                        "appear_times": 0,
                        "slide_numbers": set(),
                        "relative_area": shape.area / self.slide_area * 100,
                    }
                self.image_stats[image_path]["appear_times"] += 1
                self.image_stats[image_path]["slide_numbers"].add(slide_index + 1)
        for image_path, stats in self.image_stats.items():
            stats["slide_numbers"] = sorted(list(stats["slide_numbers"]))
            ranges = self._find_ranges(stats["slide_numbers"])
            top_ranges = sorted(ranges, key=lambda x: x[1] - x[0], reverse=True)[:3]
            top_ranges_str = ", ".join(
                [f"{r[0]}-{r[1]}" if r[0] != r[1] else f"{r[0]}" for r in top_ranges]
            )
            stats["top_ranges_str"] = top_ranges_str

    def _find_ranges(self, numbers):
        """
        Find consecutive ranges in a list of numbers.
        """
        ranges = []
        start = numbers[0]
        end = numbers[0]
        for num in numbers[1:]:
            if num == end + 1:
                end = num
            else:
                ranges.append((start, end))
                start = num
                end = num
        ranges.append((start, end))
        return ranges
