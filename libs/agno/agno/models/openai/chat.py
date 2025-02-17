from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import AudioOutput
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger
from agno.utils.openai import add_audio_to_message, add_images_to_message

try:
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai import AsyncOpenAI as AsyncOpenAIClient
    from openai import OpenAI as OpenAIClient
    from openai.types.chat import ChatCompletionAudio
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )
    from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class OpenAIChat(Model):
    """
    A class for interacting with OpenAI models.

    For more information, see: https://platform.openai.com/docs/api-reference/chat/create
    """

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"
    supports_structured_outputs: bool = True

    # Request parameters
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modalities: Optional[List[str]] = None
    audio: Optional[Dict[str, Any]] = None
    presence_penalty: Optional[float] = None
    response_format: Optional[Any] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    user: Optional[str] = None
    top_p: Optional[float] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # OpenAI clients
    client: Optional[OpenAIClient] = None
    async_client: Optional[AsyncOpenAIClient] = None

    # Internal parameters. Not used for API requests
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False

    # The role to map the message role to.
    role_map = {
        "system": "developer",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENAI_API_KEY")
            if not self.api_key:
                logger.error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }
        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}
        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        self.client = OpenAIClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        if self.async_client:
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        return AsyncOpenAIClient(**client_params)

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "store": self.store,
            "reasoning_effort": self.reasoning_effort,
            "frequency_penalty": self.frequency_penalty,
            "logit_bias": self.logit_bias,
            "logprobs": self.logprobs,
            "top_logprobs": self.top_logprobs,
            "max_tokens": self.max_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "modalities": self.modalities,
            "audio": self.audio,
            "presence_penalty": self.presence_penalty,
            "response_format": self.response_format,
            "seed": self.seed,
            "stop": self.stop,
            "temperature": self.temperature,
            "user": self.user,
            "top_p": self.top_p,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "metadata": self.metadata
        }
        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params["tools"] = self._tools
            if self.tool_choice is not None:
                request_params["tool_choice"] = self.tool_choice
        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "store": self.store,
                "frequency_penalty": self.frequency_penalty,
                "logit_bias": self.logit_bias,
                "logprobs": self.logprobs,
                "top_logprobs": self.top_logprobs,
                "max_tokens": self.max_tokens,
                "max_completion_tokens": self.max_completion_tokens,
                "modalities": self.modalities,
                "audio": self.audio,
                "presence_penalty": self.presence_penalty,
                "response_format": self.response_format
                if isinstance(self.response_format, dict)
                else str(self.response_format),
                "seed": self.seed,
                "stop": self.stop,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "user": self.user,
                "extra_headers": self.extra_headers,
                "extra_query": self.extra_query,
            }
        )
        if self._tools is not None:
            model_dict["tools"] = self._tools
            if self.tool_choice is not None:
                model_dict["tool_choice"] = self.tool_choice
            else:
                model_dict["tool_choice"] = "auto"
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        if message.role == "user":
            if message.images is not None:
                message = add_images_to_message(message=message, images=message.images)

            if message.audio is not None:
                message = add_audio_to_message(message=message, audio=message.audio)

            if message.videos is not None:
                logger.warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message.tool_calls = None

        message_dict = message.serialize_for_model()
        message_dict["role"] = self.role_map[message_dict["role"]]

        return message_dict

    def invoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        """
        Send a chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        try:
            if self.response_format is not None and self.structured_outputs:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return self.get_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self._format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")

            return self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        """
        Sends an asynchronous chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            ChatCompletion: The chat completion response from the API.
        """
        try:
            if self.response_format is not None and self.structured_outputs:
                if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                    return await self.get_async_client().beta.chat.completions.parse(
                        model=self.id,
                        messages=[self._format_message(m) for m in messages],  # type: ignore
                        **self.request_kwargs,
                    )
                else:
                    raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")
            return await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionChunk]:
        """
        Send a streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ChatCompletionChunk]: An iterator of chat completion chunks.
        """
        try:
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.request_kwargs,
            )  # type: ignore
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[ChatCompletionChunk]:
        """
        Sends an asynchronous streaming chat completion request to the OpenAI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        try:
            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                stream_options={"include_usage": True},
                **self.request_kwargs,
            )
            async for chunk in async_stream:
                yield chunk
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(e, self.name, self.id) from e

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[ChoiceDeltaToolCall]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[ChoiceDeltaToolCall]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        if not tool_calls_data:
            return []

        tool_calls: List[Dict[str, Any]] = []
        current_index = 0
        for _tool_call in tool_calls_data:
            if not _tool_call:
                continue

            # Use current_index if index is not available
            _index = getattr(_tool_call, "index", None)
            if _index is None:
                _index = current_index
                current_index += 1

            _tool_call_id = getattr(_tool_call, "id", None)
            _tool_call_type = getattr(_tool_call, "type", None)
            _function = getattr(_tool_call, "function", None)
            _function_name = getattr(_function, "name", None) if _function else None
            _function_arguments = getattr(_function, "arguments", None) if _function else None

            # Ensure _index is valid
            while len(tool_calls) <= _index:
                tool_calls.append({})

            tool_call_entry = tool_calls[_index]
            if not tool_call_entry:
                tool_call_entry["id"] = _tool_call_id
                tool_call_entry["type"] = _tool_call_type
                tool_call_entry["function"] = {
                    "name": _function_name or "",
                    "arguments": _function_arguments or "",
                }
            else:
                if _function_name:
                    tool_call_entry["function"]["name"] += _function_name
                if _function_arguments:
                    tool_call_entry["function"]["arguments"] += _function_arguments
                if _tool_call_id:
                    tool_call_entry["id"] = _tool_call_id
                if _tool_call_type:
                    tool_call_entry["type"] = _tool_call_type
        return tool_calls

    def parse_provider_response(self, response: Union[ChatCompletion, ParsedChatCompletion]) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.

        Args:
            response: Response from invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Get response message
        response_message = response.choices[0].message

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.parsed  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            logger.warning(f"Error retrieving structured outputs: {e}")

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")

        # Add audio transcript to content if available
        response_audio: Optional[ChatCompletionAudio] = response_message.audio
        if response_audio and response_audio.transcript and not model_response.content:
            model_response.content = response_audio.transcript

        # Add audio if present
        if hasattr(response_message, "audio") and response_message.audio is not None:
            try:
                model_response.audio = AudioOutput(
                    id=response_message.audio.id,
                    content=response_message.audio.data,
                    expires_at=response_message.audio.expires_at,
                    transcript=response_message.audio.transcript,
                )
            except Exception as e:
                logger.warning(f"Error processing audio: {e}")

        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content is not None:
            model_response.reasoning_content = response_message.reasoning_content

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ProviderResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()
        if response_delta.choices and len(response_delta.choices) > 0:
            delta: ChoiceDelta = response_delta.choices[0].delta

            # Add content
            if delta.content is not None:
                model_response.content = delta.content

            # Add tool calls
            if delta.tool_calls is not None:
                model_response.tool_calls = delta.tool_calls  # type: ignore

            # Add audio if present
            if hasattr(delta, "audio") and delta.audio is not None:
                try:
                    model_response.audio = AudioOutput(
                        id=delta.audio.id,
                        content=delta.audio.data,
                        expires_at=delta.audio.expires_at,
                        transcript=delta.audio.transcript,
                    )
                except Exception as e:
                    logger.warning(f"Error processing audio: {e}")

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response
