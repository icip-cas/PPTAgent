from dataclasses import asdict, dataclass
from functools import partial
from math import ceil
from typing import Optional

import tiktoken
import yaml
from jinja2 import Environment, StrictUndefined, Template
from PIL import Image
from torch import Tensor, cosine_similarity

from pptagent.llms import LLM, AsyncLLM
from pptagent.utils import get_json_from_response, package_join

ENCODING = tiktoken.encoding_for_model("gpt-4o")


@dataclass
class Turn:
    """
    A class to represent a turn in a conversation.
    """

    id: int
    prompt: str
    response: str
    message: list
    retry: int = -1
    images: list[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    embedding: Tensor = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if k != "embedding"}

    def calc_token(self):
        """
        Calculate the number of tokens for the turn.
        """
        if self.images is not None:
            self.input_tokens += calc_image_tokens(self.images)
        self.input_tokens += len(ENCODING.encode(self.prompt))
        self.output_tokens = len(ENCODING.encode(self.response))

    def __eq__(self, other):
        return self is other


class Agent:
    """
    An agent, defined by its instruction template and model.
    """

    def __init__(
        self,
        name: str,
        llm_mapping: dict[str, LLM | AsyncLLM],
        text_model: Optional[LLM | AsyncLLM] = None,
        record_cost: bool = False,
        config: Optional[dict] = None,
        env: Optional[Environment] = None,
    ):
        """
        Initialize the Agent.

        Args:
            name (str): The name of the role.
            env (Environment): The Jinja2 environment.
            record_cost (bool): Whether to record the token cost.
            llm (LLM): The language model.
            config (dict): The configuration.
            text_model (LLM): The text embedding model.
        """
        self.name = name
        self.config = config
        if self.config is None:
            with open(package_join("roles", f"{name}.yaml")) as f:
                self.config = yaml.safe_load(f)
                assert isinstance(self.config, dict), "Agent config must be a dict"
        self.llm_mapping = llm_mapping
        self.llm = self.llm_mapping[self.config["use_model"]]
        self.model = self.llm.model
        self.record_cost = record_cost
        self.text_model = text_model
        self.return_json = self.config.get("return_json", False)
        self.system_message = self.config["system_prompt"]
        self.prompt_args = set(self.config["jinja_args"])
        self.env = env
        if self.env is None:
            self.env = Environment(undefined=StrictUndefined)
        self.template = self.env.from_string(self.config["template"])
        self.retry_template = Template(
            """The previous output is invalid, please carefully analyze the traceback and feedback information, correct errors happened before.
            feedback:
            {{feedback}}
            traceback:
            {{traceback}}
            Give your corrected output in the same format without including the previous output:
            """
        )
        self.input_tokens = 0
        self.output_tokens = 0
        self._history: list[Turn] = []
        run_args = self.config.get("run_args", {})
        self.llm.__call__ = partial(self.llm.__call__, **run_args)
        self.system_tokens = len(ENCODING.encode(self.system_message))

    def calc_cost(self, turns: list[Turn]):
        """
        Calculate the cost of a list of turns.
        """
        for turn in turns[:-1]:
            self.input_tokens += turn.input_tokens
            self.input_tokens += turn.output_tokens
        self.input_tokens += turns[-1].input_tokens
        self.output_tokens += turns[-1].output_tokens
        self.input_tokens += self.system_tokens

    def get_history(self, similar: int, recent: int, prompt: str):
        """
        Get the conversation history.
        """
        history = self._history[-recent:] if recent > 0 else []
        if similar > 0:
            assert isinstance(self.text_model, LLM), "text_model must be a LLM"
            embedding = self.text_model.get_embedding(prompt)
            history.sort(key=lambda x: cosine_similarity(embedding, x.embedding))
            for turn in history:
                if len(history) > similar + recent:
                    break
                if turn not in history:
                    history.append(turn)
        history.sort(key=lambda x: x.id)
        return history

    def retry(self, feedback: str, traceback: str, turn_id: int, error_idx: int):
        """
        Retry a failed turn with feedback and traceback.
        """
        assert error_idx > 0, "error_idx must be greater than 0"
        prompt = self.retry_template.render(feedback=feedback, traceback=traceback)
        history = [t for t in self._history if t.id == turn_id]
        history_msg = []
        for turn in history:
            history_msg.extend(turn.message)
        response, message = self.llm(
            prompt,
            history=history_msg,
            return_message=True,
        )
        turn = Turn(
            id=turn_id,
            prompt=prompt,
            response=response,
            message=message,
            retry=error_idx,
        )
        return self.__post_process__(response, history, turn)

    @property
    def next_turn_id(self):
        if len(self._history) == 0:
            return 0
        return max(t.id for t in self._history) + 1

    @property
    def history(self):
        return sorted(self._history, key=lambda x: (x.id, x.retry))

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, model={self.model})"

    def __call__(
        self,
        images: list[str] = None,
        recent: int = 0,
        similar: int = 0,
        **jinja_args,
    ):
        """
        Call the agent with prompt arguments.

        Args:
            images (list[str]): A list of image file paths.
            recent (int): The number of recent turns to include.
            similar (int): The number of similar turns to include.
            **jinja_args: Additional arguments for the Jinja2 template.

        Returns:
            The response from the role.
        """
        if isinstance(images, str):
            images = [images]
        assert self.prompt_args == set(
            jinja_args.keys()
        ), f"Invalid arguments, expected: {self.prompt_args}, got: {jinja_args.keys()}"
        prompt = self.template.render(**jinja_args)
        history = self.get_history(similar, recent, prompt)
        history_msg = []
        for turn in history:
            history_msg.extend(turn.message)

        response, message = self.llm(
            prompt,
            system_message=self.system_message,
            history=history_msg,
            images=images,
            return_message=True,
        )
        turn = Turn(
            id=self.next_turn_id,
            prompt=prompt,
            response=response,
            message=message,
            images=images,
        )
        return turn.id, self.__post_process__(response, history, turn, similar)

    def __post_process__(
        self, response: str, history: list[Turn], turn: Turn, similar: int = 0
    ) -> str | dict:
        """
        Post-process the response from the agent.
        """
        self._history.append(turn)
        if similar > 0:
            turn.embedding = self.text_model.get_embedding(turn.prompt)
        if self.record_cost:
            turn.calc_token()
            self.calc_cost(history + [turn])
        if self.return_json:
            response = get_json_from_response(response)
        return response


class AsyncAgent(Agent):
    """
    An agent, defined by its instruction template and model.
    """

    def __init__(
        self,
        name: str,
        llm_mapping: dict[str, AsyncLLM],
        text_model: Optional[AsyncLLM] = None,
        record_cost: bool = False,
        config: Optional[dict] = None,
        env: Optional[Environment] = None,
    ):
        super().__init__(name, llm_mapping, text_model, record_cost, config, env)
        assert isinstance(self.llm, AsyncLLM), "You should use AsyncLLM for AsyncAgent"

    async def retry(self, feedback: str, traceback: str, turn_id: int, error_idx: int):
        """
        Retry a failed turn with feedback and traceback.
        """
        assert error_idx > 0, "error_idx must be greater than 0"
        prompt = self.retry_template.render(feedback=feedback, traceback=traceback)
        history = [t for t in self._history if t.id == turn_id]
        history_msg = []
        for turn in history:
            history_msg.extend(turn.message)
        response, message = await self.llm(
            prompt,
            history=history_msg,
            return_message=True,
        )
        turn = Turn(
            id=turn_id,
            prompt=prompt,
            response=response,
            message=message,
            retry=error_idx,
        )
        return await self.__post_process__(response, history, turn)

    async def __call__(
        self,
        images: list[str] = None,
        recent: int = 0,
        similar: int = 0,
        **jinja_args,
    ):
        """
        Call the agent with prompt arguments.

        Args:
            images (list[str]): A list of image file paths.
            recent (int): The number of recent turns to include.
            similar (int): The number of similar turns to include.
            **jinja_args: Additional arguments for the Jinja2 template.

        Returns:
            The response from the role.
        """
        if isinstance(images, str):
            images = [images]
        assert self.prompt_args == set(
            jinja_args.keys()
        ), f"Invalid arguments, expected: {self.prompt_args}, got: {jinja_args.keys()}"
        prompt = self.template.render(**jinja_args)
        history = await self.get_history(similar, recent, prompt)
        history_msg = []
        for turn in history:
            history_msg.extend(turn.message)

        response, message = await self.llm(
            prompt,
            system_message=self.system_message,
            history=history_msg,
            images=images,
            return_message=True,
        )
        turn = Turn(
            id=self.next_turn_id,
            prompt=prompt,
            response=response,
            message=message,
            images=images,
        )
        return turn.id, await self.__post_process__(response, history, turn, similar)

    async def get_history(self, similar: int, recent: int, prompt: str):
        """
        Get the conversation history.
        """
        history = self._history[-recent:] if recent > 0 else []
        if similar > 0:
            embedding = await self.text_model.get_embedding(prompt)
            history.sort(key=lambda x: cosine_similarity(embedding, x.embedding))
            for turn in history:
                if len(history) > similar + recent:
                    break
                if turn not in history:
                    history.append(turn)
        history.sort(key=lambda x: x.id)
        return history

    async def __post_process__(
        self, response: str, history: list[Turn], turn: Turn, similar: int = 0
    ):
        """
        Post-process the response from the agent.
        """
        self._history.append(turn)
        if similar > 0:
            turn.embedding = await self.text_model.get_embedding(turn.prompt)
        if self.record_cost:
            turn.calc_token()
            self.calc_cost(history + [turn])
        if self.return_json:
            response = get_json_from_response(response)
        return response


def calc_image_tokens(images: list[str]):
    """
    Calculate the number of tokens for a list of images.
    """
    tokens = 0
    for image in images:
        with open(image, "rb") as f:
            width, height = Image.open(f).size
        if width > 1024 or height > 1024:
            if width > height:
                height = int(height * 1024 / width)
                width = 1024
            else:
                width = int(width * 1024 / height)
                height = 1024
        h = ceil(height / 512)
        w = ceil(width / 512)
        tokens += 85 + 170 * h * w
    return tokens
