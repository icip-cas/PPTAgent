import os
import tempfile
import zipfile
from glob import glob
from os.path import join

import aiofiles
import aiohttp
from PIL import Image

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pptagent.llms import AsyncLLM
from pptagent.utils import (
    Language,
    get_logger,
    is_image_path,
)

logger = get_logger(__name__)

# Lazy loading cache for the language ID model
_LID_MODEL = None


def _get_lid_model():
    from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE

    """Get the language ID model, loading it lazily on first access."""
    global _LID_MODEL
    if _LID_MODEL is None:
        from fasttext import load_model
        from huggingface_hub import hf_hub_download

        lid_pattern = join(
            HUGGINGFACE_HUB_CACHE,
            "models--julien-c--fasttext-language-id",
            "*/*/lid.176.bin",
        )
        lid_files = glob(lid_pattern)
        if lid_files:
            _LID_MODEL = load_model(lid_files[0])
        else:
            _LID_MODEL = load_model(
                hf_hub_download(
                    repo_id="julien-c/fasttext-language-id",
                    filename="lid.176.bin",
                )
            )
    return _LID_MODEL


MINERU_API = os.environ.get("MINERU_API", None)
if MINERU_API is None:
    logger.debug("MINERU_API is not set, PDF parsing is not available")


class ModelManager:
    """
    A class to manage models.
    """

    def __init__(
        self,
        api_base: str | None = None,
        language_model_name: str | None = None,
        vision_model_name: str | None = None,
    ):
        """Initialize models from environment variables after instance creation"""
        # Check for OpenRouter API key
        openrouter_api_key = os.environ.get("OPEN_ROUTER_API_KEY", None)
        openai_api_key = os.environ.get("OPENAI_API_KEY", None)
        
        # Determine API base URL and key
        if api_base is None:
            if openrouter_api_key:
                # Use OpenRouter if API key is provided
                api_base = os.environ.get("API_BASE", "https://openrouter.ai/api/v1")
                api_key = openrouter_api_key
                logger.info("Using OpenRouter API")
            else:
                # Fall back to OpenAI or custom API_BASE
                api_base = os.environ.get("API_BASE", None)
                api_key = openai_api_key
        else:
            # If api_base is explicitly provided, use it
            api_key = openrouter_api_key if openrouter_api_key else openai_api_key
        
        if language_model_name is None:
            # Default to OpenRouter format if using OpenRouter, otherwise OpenAI format
            # Note: Must use a model that supports structured outputs (json_schema)
            # Supported models: gpt-4o, gpt-4-turbo, gpt-3.5-turbo-1106+
            if openrouter_api_key:
                language_model_name = os.environ.get("LANGUAGE_MODEL", "openai/gpt-4o")
            else:
                language_model_name = os.environ.get("LANGUAGE_MODEL", "gpt-4.1")
        if vision_model_name is None:
            # Default to OpenRouter format if using OpenRouter, otherwise OpenAI format
            # Vision models are used for analyzing images, slides, and visual content
            if openrouter_api_key:
                # Use GPT-4o which has vision capabilities, or fallback to language model
                vision_model_name = os.environ.get("VISION_MODEL", "openai/gpt-4o")
            else:
                vision_model_name = os.environ.get("VISION_MODEL", "gpt-4.1")
        self._image_model = None

        # Initialize models with API key
        self.language_model = AsyncLLM(language_model_name, api_base, api_key)
        self.vision_model = AsyncLLM(vision_model_name, api_base, api_key)

    @property
    def image_model(self):
        import torch

        if self._image_model is None:
            self._image_model = get_image_model(
                device="cuda" if torch.cuda.is_available() else "cpu"
            )
        return self._image_model

    async def test_connections(self) -> bool:
        """Test connections for all LLM models

        Returns:
            bool: True if all connections are successful, False otherwise
        """
        try:
            assert await self.language_model.test_connection()
            assert await self.vision_model.test_connection()
        except Exception as _:
            return False
        return True


def language_id(text: str) -> Language:
    model = _get_lid_model()
    return Language(
        lid=model.predict(text[:1024].replace("\n", ""))[0][0].replace("__label__", "")
    )


def get_image_model(device: str = None):
    import torch
    from transformers import AutoModel, AutoProcessor

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


async def parse_pdf(pdf_path: str, output_folder: str):
    """
    Parse a PDF file and extract text and images.

    Args:
        pdf_path (str): The path to the PDF file.
        output_path (str): The root directory to save the extracted content.

    Returns:
        str: The path to the extracted folder
    """
    assert MINERU_API is not None, "MINERU_API is not set"
    os.makedirs(output_folder, exist_ok=True)

    async with aiofiles.open(pdf_path, "rb") as f:
        pdf_content = await f.read()

    data = aiohttp.FormData()
    data.add_field(
        "files",
        pdf_content,
        filename=os.path.basename(pdf_path),
        content_type="application/pdf",
    )
    data.add_field("return_images", "True")
    data.add_field("response_format_zip", "True")

    async with aiohttp.ClientSession() as session:
        async with session.post(MINERU_API, data=data) as response:
            response.raise_for_status()
            content = await response.read()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(content)
                zip_path = tmp.name

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                top_level = {
                    name.split("/", 1)[0] for name in zip_ref.namelist() if name.strip()
                }
                if len(top_level) != 1:
                    raise RuntimeError("Expected exactly one top-level folder in zip")
                prefix = list(top_level)[0] + "/"

                for member in zip_ref.infolist():
                    filename = member.filename
                    dest_path = os.path.join(
                        output_folder, filename.removeprefix(prefix)
                    )

                    if not member.is_dir():
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                            dst.write(src.read())


def get_image_embedding(
    image_dir: str, extractor, model, batchsize: int = 16
) -> dict[str, list[float]]:
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
    import torch
    import torchvision.transforms as T

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
        image = Image.open(join(image_dir, file)).convert("RGB")
        inputs.append(transform(image))
        if len(inputs) % batchsize == 0 or file == images[-1]:
            batch = {"pixel_values": torch.stack(inputs).to(model.device)}
            embeddings.extend(model(**batch).last_hidden_state.detach())
            inputs.clear()
    return {
        image: embedding.flatten().tolist()
        for image, embedding in zip(images, embeddings)
    }


def images_cosine_similarity(embeddings: list[list[float]]) -> list[float]:
    """
    Calculate the cosine similarity matrix for a list of embeddings.
    Args:
        embeddings (list[torch.Tensor]): A list of image embeddings.

    Returns:
        torch.Tensor: A NxN similarity matrix.
    """
    import torch

    embeddings = [torch.tensor(embedding) for embedding in embeddings]
    sim_matrix = torch.zeros((len(embeddings), len(embeddings)))
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sim_matrix[i, j] = sim_matrix[j, i] = torch.nn.functional.cosine_similarity(
                embeddings[i], embeddings[j], -1
            )
    return sim_matrix.tolist()


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def average_distance(
    similarity: list[list[float]], idx: int, cluster_idx: list[int]
) -> float:
    """
    Calculate the average distance between a point (idx) and a cluster (cluster_idx).

    Args:
        similarity (list[list[float]]): The similarity matrix.
        idx (int): The index of the point.
        cluster_idx (list): The indices of the cluster.

    Returns:
        float: The average distance.
    """
    import torch

    similarity = torch.tensor(similarity)
    if idx in cluster_idx:
        return 0
    total_similarity = 0
    for idx_in_cluster in cluster_idx:
        total_similarity += similarity[idx, idx_in_cluster]
    return total_similarity / len(cluster_idx)


def get_cluster(similarity: list[list[float]], sim_bound: float = 0.65):
    """
    Cluster points based on similarity.

    Args:
        similarity (list[list[float]]): The similarity matrix.
        sim_bound (float): The similarity threshold for clustering.

    Returns:
        list: A list of clusters.
    """
    import torch

    similarity = torch.tensor(similarity)
    sim_copy = similarity.clone()
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
                # append the remaining points individual cluster
                for i in range(num_points):
                    if not added[i]:
                        clusters.append([i])
                break
            i, j = torch.unravel_index(torch.argmax(sim_copy), sim_copy.shape)
            clusters.append([int(i), int(j)])
            added[i] = True
            added[j] = True
            sim_copy[i, :] = 0
            sim_copy[:, i] = 0
            sim_copy[j, :] = 0
            sim_copy[:, j] = 0

    return clusters
