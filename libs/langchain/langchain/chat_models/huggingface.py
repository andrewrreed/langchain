"""Hugging Face Chat Wrapper."""
from typing import Any, List, Optional, Union, Type

from langchain.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain.chat_models.base import BaseChatModel
from langchain.llms import (
    HuggingFaceEndpoint,
    HuggingFaceHub,
    HuggingFaceTextGenInference,
)
from langchain.llms.base import LLM

from langchain.schema import (
    AIMessage,
    BaseMessage,
    ChatGeneration,
    ChatResult,
    HumanMessage,
    LLMResult,
    SystemMessage,
)

from transformers import AutoTokenizer

DEFAULT_SYSTEM_PROMPT = """You are a helpful, respectful, and honest assistant."""


class ChatHuggingFace(BaseChatModel):
    """
    Wrapper for using Hugging Face LLM's as ChatModels.

    Works with `HuggingFaceTextGenInference`, `HuggingFaceEndpoint`,
    and `HuggingFaceHub` LLMs.

    Upon instantiating this class, the model_id is resolved from the url
    provided to the LLM, and the appropriate tokenizer is loaded from
    the HuggingFace Hub.

    Adapted from: https://python.langchain.com/docs/integrations/chat/llama2_chat
    """

    llm: LLM
    system_message: SystemMessage = SystemMessage(content=DEFAULT_SYSTEM_PROMPT)
    tokenizer: AutoTokenizer = None
    model_id: str = None # type: ignore

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        if not isinstance(self.llm, (HuggingFaceEndpoint, HuggingFaceTextGenInference, HuggingFaceHub)):
            raise ValueError(f"LLM type not supported for ChatHuggingFace: {type(self.llm)}")

        self._resolve_model_id()
        self.tokenizer = (
            AutoTokenizer.from_pretrained(self.model_id)
            if self.tokenizer is None
            else self.tokenizer
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        llm_input = self._to_chat_prompt(messages)
        llm_result = self.llm._generate(
            prompts=[llm_input], stop=stop, run_manager=run_manager, **kwargs
        )
        return self._to_chat_result(llm_result)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        llm_input = self._to_chat_prompt(messages)
        llm_result = await self.llm._agenerate(
            prompts=[llm_input], stop=stop, run_manager=run_manager, **kwargs
        )
        return self._to_chat_result(llm_result)

    def _to_chat_prompt(
        self,
        messages: List[BaseMessage],
    ) -> str:
        """Convert a list of messages into a prompt format expected by wrapped LLM."""
        if not messages:
            raise ValueError("at least one HumanMessage must be provided")

        if not isinstance(messages[0], SystemMessage):
            messages = [self.system_message] + messages

        if not isinstance(messages[1], HumanMessage):
            raise ValueError(
                "messages list must start with a SystemMessage or UserMessage"
            )

        if not isinstance(messages[-1], HumanMessage):
            raise ValueError("last message must be a HumanMessage")

        messages = [self._to_chatml_format(m) for m in messages]

        return self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    def _to_chatml_format(
        self, message: Union[AIMessage, SystemMessage, HumanMessage]
    ) -> dict:
        """Convert LangChain message to ChatML format."""

        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, HumanMessage):
            role = "user"
        else:
            raise ValueError(f"Unknown message type: {type(message)}")

        return {"role": role, "content": message.content}

    @staticmethod
    def _to_chat_result(llm_result: LLMResult) -> ChatResult:
        chat_generations = []

        for g in llm_result.generations[0]:
            chat_generation = ChatGeneration(
                message=AIMessage(content=g.text), generation_info=g.generation_info
            )
            chat_generations.append(chat_generation)

        return ChatResult(
            generations=chat_generations, llm_output=llm_result.llm_output
        )

    def _resolve_model_id(self) -> None:
        """Resolve the model_id from the LLM's inference_server_url"""

        from huggingface_hub import list_inference_endpoints

        available_endpoints = list_inference_endpoints("*")

        if isinstance(self.llm, HuggingFaceTextGenInference):
            endpoint_url = self.llm.inference_server_url

        elif isinstance(self.llm, HuggingFaceEndpoint):
            endpoint_url = self.llm.endpoint_url

        elif isinstance(self.llm, HuggingFaceHub):
            # no need to look up model_id for HuggingFaceHub LLM
            self.model_id = self.llm.repo_id
            return

        else:
            raise ValueError(f"Unknown LLM type: {type(self.llm)}")

        for endpoint in available_endpoints:
            if endpoint.url == endpoint_url:
                self.model_id = endpoint.repository

        if not self.model_id:
            raise ValueError(
                "Failed to resolve model_id"
                f"Could not find model id for inference server provided: {endpoint_url}"
                "Check to ensure the Hugging Face token you're using has access to the endpoint."
            )

    @property
    def _llm_type(self) -> str:
        return f"{self.model_id.lower()}-style"
