from dataclasses import dataclass

from pydantic import BaseModel

from pptagent.llms import LLM, AsyncLLM
from pptagent.utils import get_logger, tenacity_decorator

logger = get_logger(__name__)


@dataclass
class LiteLLMLLM(LLM):
    """LLM wrapper that uses LiteLLM for multi-provider support."""

    def __post_init__(self) -> None:
        self.client = None

    @tenacity_decorator
    def __call__(
        self,
        content: str,
        images: str | list[str] | None = None,
        system_message: str | None = None,
        history: list | None = None,
        return_json: bool = False,
        return_message: bool = False,
        response_format: BaseModel | None = None,
        **client_kwargs,
    ) -> str | dict | list | tuple:
        import litellm

        if history is None:
            history = []
        system, message = self.format_message(content, images, system_message)
        kwargs: dict = {
            "model": self.model,
            "messages": system + history + message,
            "drop_params": True,
            **client_kwargs,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            completion = litellm.completion(**kwargs)
        except Exception as e:
            logger.warning("Error in LiteLLM (%s) service: %s", self.model, e)
            raise
        response = completion.choices[0].message.content
        message.append({"role": "assistant", "content": response})
        return self.__post_process__(response, message, return_json, return_message)

    def test_connection(self) -> bool:
        import litellm

        try:
            litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                drop_params=True,
                **({"api_key": self.api_key} if self.api_key else {}),
                **({"api_base": self.base_url} if self.base_url else {}),
            )
            return True
        except Exception as e:
            logger.warning("LiteLLM connection test failed: %s", e)
            return False

    def gen_image(self, prompt: str, n: int = 1, **kwargs) -> str:
        import litellm

        response = litellm.image_generation(
            model=self.model,
            prompt=prompt,
            n=n,
            drop_params=True,
            **({"api_key": self.api_key} if self.api_key else {}),
            **({"api_base": self.base_url} if self.base_url else {}),
            **kwargs,
        )
        return response.data[0].b64_json

    def to_async(self) -> "AsyncLiteLLMLLM":
        return AsyncLiteLLMLLM(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )


@dataclass
class AsyncLiteLLMLLM(AsyncLLM):
    """Async LLM wrapper that uses LiteLLM for multi-provider support."""

    def __post_init__(self) -> None:
        self.client = None
        self.batch = None

    @tenacity_decorator
    async def __call__(
        self,
        content: str,
        images: str | list[str] | None = None,
        system_message: str | None = None,
        history: list | None = None,
        return_json: bool = False,
        return_message: bool = False,
        response_format: BaseModel | None = None,
        **client_kwargs,
    ) -> str | dict | tuple:
        import litellm

        if history is None:
            history = []
        system, message = self.format_message(content, images, system_message)
        kwargs: dict = {
            "model": self.model,
            "messages": system + history + message,
            "drop_params": True,
            **client_kwargs,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            completion = await litellm.acompletion(**kwargs)
        except Exception as e:
            logger.error("Error in AsyncLiteLLMLLM call: %s", e)
            raise
        response = completion.choices[0].message.content
        message.append({"role": "assistant", "content": response})
        return self.__post_process__(response, message, return_json, return_message)

    async def test_connection(self) -> bool:
        import litellm

        try:
            await litellm.acompletion(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                drop_params=True,
                **({"api_key": self.api_key} if self.api_key else {}),
                **({"api_base": self.base_url} if self.base_url else {}),
            )
            return True
        except Exception as e:
            logger.warning("LiteLLM async connection test failed: %s", e)
            return False

    async def gen_image(self, prompt: str, n: int = 1, **kwargs) -> str:
        import litellm

        response = await litellm.aimage_generation(
            model=self.model,
            prompt=prompt,
            n=n,
            response_format="b64_json",
            drop_params=True,
            **({"api_key": self.api_key} if self.api_key else {}),
            **({"api_base": self.base_url} if self.base_url else {}),
            **kwargs,
        )
        return response.data[0].b64_json

    def to_sync(self) -> LiteLLMLLM:
        return LiteLLMLLM(
            model=self.model, base_url=self.base_url, api_key=self.api_key
        )
