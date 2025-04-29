import json
import os
from copy import deepcopy
from typing import Optional

import numpy as np
import torch
import torchvision.transforms as T
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from PIL import Image
from transformers import AutoModel, AutoProcessor

from pptagent.llms import LLM, AsyncLLM
from pptagent.presentation import Presentation, SlidePage
from pptagent.utils import get_logger, is_image_path, pjoin

logger = get_logger(__name__)


class ModelManager:
    """
    A class to manage models.
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        language_model_name: Optional[str] = None,
        vision_model_name: Optional[str] = None,
        text_model_name: Optional[str] = None,
    ):
        """Initialize models from environment variables after instance creation"""
        if api_base is None:
            api_base = os.environ.get("API_BASE", None)
        if language_model_name is None:
            language_model_name = os.environ.get("LANGUAGE_MODEL", "gpt-4.1")
        if vision_model_name is None:
            vision_model_name = os.environ.get("VISION_MODEL", "gpt-4.1")
        if text_model_name is None:
            text_model_name = os.environ.get("TEXT_MODEL", "text-embedding-3-small")
        self._image_model = None
        self._marker_model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.language_model = AsyncLLM(language_model_name, api_base)
        self.vision_model = AsyncLLM(vision_model_name, api_base)
        self.text_model = AsyncLLM(text_model_name, api_base)

    @property
    def image_model(self):
        if self._image_model is None:
            self._image_model = get_image_model(device=self.device)
        return self._image_model

    @property
    def marker_model(self):
        if self._marker_model is None:
            self._marker_model = create_model_dict(
                device=self.device, dtype=torch.float16
            )
        return self._marker_model

    async def test_connections(self) -> bool:
        """Test connections for all LLM models

        Returns:
            bool: True if all connections are successful, False otherwise
        """
        try:
            assert await self.language_model.test_connection()
            assert await self.vision_model.test_connection()
            assert await self.text_model.test_connection()
        except:
            return False
        return True


def prs_dedup(
    presentation: Presentation,
    model: LLM,
    threshold: float = 0.8,
) -> list[SlidePage]:
    """
    Deduplicate slides in a presentation based on text similarity.

    Args:
        presentation (Presentation): The presentation object containing slides.
        model: The model used for generating text embeddings.
        batchsize (int): The batch size for processing slides.
        threshold (float): The similarity threshold for deduplication.

    Returns:
        list: A list of removed duplicate slides.
    """
    text_embeddings = model.get_embedding([i.to_text() for i in presentation.slides])
    pre_embedding = text_embeddings[0]
    slide_idx = 1
    duplicates = []
    while slide_idx < len(presentation):
        cur_embedding = text_embeddings[slide_idx]
        if torch.cosine_similarity(pre_embedding, cur_embedding, -1) > threshold:
            duplicates.append(slide_idx - 1)
        slide_idx += 1
        pre_embedding = cur_embedding
    return [presentation.slides.pop(i) for i in reversed(duplicates)]


def get_image_model(device: str = None):
    """
    Initialize and return an image model and its feature extractor.

    Args:
        device (str): The device to run the model on.

    Returns:
        tuple: A tuple containing the feature extractor and the image model.
    """
    model_base = "google/vit-base-patch16-224-in21k"
    return (
        AutoProcessor.from_pretrained(
            model_base,
            torch_dtype=torch.float16,
            device_map=device,
            use_fast=True,
        ),
        AutoModel.from_pretrained(
            model_base,
            torch_dtype=torch.float16,
            device_map=device,
        ).eval(),
    )


def parse_pdf(
    pdf_path: str,
    output_path: str,
    model_lst: list,
) -> str:
    """
    Parse a PDF file and extract text and images.

    Args:
        pdf_path (str): The path to the PDF file.
        output_path (str): The directory to save the extracted content.
        model_lst (list): A list of models for processing the PDF.

    Returns:
        str: The full text extracted from the PDF.
    """
    os.makedirs(output_path, exist_ok=True)
    config_parser = ConfigParser(
        {
            "output_format": "markdown",
        }
    )
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=model_lst,
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
    )
    rendered = converter(pdf_path)
    full_text, _, images = text_from_rendered(rendered)
    with open(pjoin(output_path, "source.md"), "w+", encoding="utf-8") as f:
        f.write(full_text)
    for filename, image in images.items():
        image_filepath = os.path.join(output_path, filename)
        image.save(image_filepath, "JPEG")
    with open(pjoin(output_path, "meta.json"), "w+", encoding="utf-8") as f:
        f.write(json.dumps(rendered.metadata, indent=4))

    return full_text


def get_image_embedding(
    image_dir: str, extractor, model, batchsize: int = 16
) -> dict[str, torch.Tensor]:
    """
    Generate image embeddings for images in a directory.

    Args:
        image_dir (str): The directory containing images.
        extractor: The feature extractor for images.
        model: The model used for generating embeddings.
        batchsize (int): The batch size for processing images.

    Returns:
        dict: A dictionary mapping image filenames to their embeddings.
    """
    transform = T.Compose(
        [
            T.Resize(int((256 / 224) * extractor.size["height"])),
            T.CenterCrop(extractor.size["height"]),
            T.ToTensor(),
            T.Normalize(mean=extractor.image_mean, std=extractor.image_std),
        ]
    )

    inputs = []
    embeddings = []
    images = [i for i in sorted(os.listdir(image_dir)) if is_image_path(i)]
    for file in images:
        image = Image.open(pjoin(image_dir, file)).convert("RGB")
        inputs.append(transform(image))
        if len(inputs) % batchsize == 0 or file == images[-1]:
            batch = {"pixel_values": torch.stack(inputs).to(model.device)}
            embeddings.extend(model(**batch).last_hidden_state.detach())
            inputs.clear()
    return {image: embedding.flatten() for image, embedding in zip(images, embeddings)}


def images_cosine_similarity(embeddings: list[torch.Tensor]) -> torch.Tensor:
    """
    Calculate the cosine similarity matrix for a list of embeddings.
    Args:
        embeddings (list[torch.Tensor]): A list of image embeddings.

    Returns:
        torch.Tensor: A NxN similarity matrix.
    """
    embeddings = [embedding for embedding in embeddings]
    sim_matrix = torch.zeros((len(embeddings), len(embeddings)))
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sim_matrix[i, j] = sim_matrix[j, i] = torch.cosine_similarity(
                embeddings[i], embeddings[j], -1
            )
    return sim_matrix


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def average_distance(
    similarity: torch.Tensor, idx: int, cluster_idx: list[int]
) -> float:
    """
    Calculate the average distance between a point (idx) and a cluster (cluster_idx).

    Args:
        similarity (np.ndarray): The similarity matrix.
        idx (int): The index of the point.
        cluster_idx (list): The indices of the cluster.

    Returns:
        float: The average distance.
    """
    if idx in cluster_idx:
        return 0
    total_similarity = 0
    for idx_in_cluster in cluster_idx:
        total_similarity += similarity[idx, idx_in_cluster]
    return total_similarity / len(cluster_idx)


def get_cluster(similarity: np.ndarray, sim_bound: float = 0.65):
    """
    Cluster points based on similarity.

    Args:
        similarity (np.ndarray): The similarity matrix.
        sim_bound (float): The similarity threshold for clustering.

    Returns:
        list: A list of clusters.
    """
    sim_copy = deepcopy(similarity)
    num_points = sim_copy.shape[0]
    clusters = []
    added = [False] * num_points

    while True:
        max_avg_dist = sim_bound
        best_cluster = None
        best_point = None

        for c in clusters:
            for point_idx in range(num_points):
                if added[point_idx]:
                    continue
                avg_dist = average_distance(sim_copy, point_idx, c)
                if avg_dist > max_avg_dist:
                    max_avg_dist = avg_dist
                    best_cluster = c
                    best_point = point_idx

        if best_point is not None:
            best_cluster.append(best_point)
            added[best_point] = True
            sim_copy[best_point, :] = 0
            sim_copy[:, best_point] = 0
        else:
            if sim_copy.max() < sim_bound:
                # append the remaining points invididual cluster
                for i in range(num_points):
                    if not added[i]:
                        clusters.append([i])
                break
            i, j = np.unravel_index(np.argmax(sim_copy), sim_copy.shape)
            clusters.append([int(i), int(j)])
            added[i] = True
            added[j] = True
            sim_copy[i, :] = 0
            sim_copy[:, i] = 0
            sim_copy[j, :] = 0
            sim_copy[:, j] = 0

    return clusters
