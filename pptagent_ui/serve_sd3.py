import base64
import sys
from datetime import datetime
from io import BytesIO
from typing import Optional, Union

import torch
import uvicorn
from diffusers import StableDiffusion3Pipeline
from fastapi import FastAPI, HTTPException
from openai.types import Image, ImagesResponse
from pydantic import BaseModel

MODEL = sys.argv[1]
SERVE_NAME = sys.argv[2]
app = FastAPI()


class ImageRequest(BaseModel):
    prompt: str
    model: Union[str, None] = None
    n: Optional[int] = 1
    quality: Optional[str] = None
    response_format: Optional[str] = None
    size: Optional[str] = None
    style: Optional[str] = None
    user: Optional[str] = None


@app.post("/v1/images/generations")
async def generate_images(request: ImageRequest) -> ImagesResponse:
    assert (
        request.model == SERVE_NAME
    ), f"Model {request.model} is not available, only {SERVE_NAME} is available"
    try:
        images = pipe(
            request.prompt,
            num_inference_steps=4,
            guidance_scale=0.0,
            num_images_per_prompt=request.n,
        ).images
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Image generation failed: {str(e)}"
        )

    image_list = []
    for image in images:
        try:
            img_io = BytesIO()
            image.save(img_io, format="PNG")
            img_io.seek(0)
            b64_json = base64.b64encode(img_io.getvalue()).decode("utf-8")

            image_data = Image(
                b64_json=b64_json,
                url=None,
                revised_prompt=None,
            )
            image_list.append(image_data)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to process image: {str(e)}"
            )
    created = int(datetime.timestamp())
    return ImagesResponse(created=created, data=image_list)


try:
    device = (
        "cuda"
        if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available() else "cpu"
    )
    pipe = StableDiffusion3Pipeline.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16
    ).to(device)
    print("Model loaded successfully")
except Exception as e:
    print(f"Error loading model: {e}")
    raise HTTPException(status_code=500, detail="Model loading failed")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
