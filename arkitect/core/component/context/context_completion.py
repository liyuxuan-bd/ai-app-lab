# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any, AsyncIterable, Dict, List

from volcenginesdkarkruntime import AsyncArk
from volcenginesdkarkruntime.resources.context import AsyncContext
from volcenginesdkarkruntime.resources.context.completions import AsyncCompletions
from volcenginesdkarkruntime.types.chat.chat_completion_message import (
    ChatCompletionMessage,
)

from arkitect.core.component.llm.model import (
    ArkChatCompletionChunk,
    ArkChatRequest,
    ArkChatResponse,
    ArkMessage,
)
from arkitect.core.component.llm.utils import convert_response_message

from .hooks import ChatHook, default_chat_hook, default_context_chat_hook
from .model import State


class _AsyncCompletions(AsyncCompletions):
    def __init__(self, client: AsyncArk, state: State, hooks: List[ChatHook]):
        self._state = state
        if len(hooks) > 0:
            self.hooks = hooks
        elif state.context_parameters and state.context_parameters.mode == "session":
            self.hooks = [default_context_chat_hook]
        else:
            # for prefix cache
            self.hooks = [default_chat_hook]
        super().__init__(client)

    async def create(
        self,
        messages: List[ArkMessage],
        stream: bool = True,
        **kwargs: Dict[str, Any],
    ) -> ArkChatResponse | AsyncIterable[ArkChatCompletionChunk]:
        parameters = (
            self._state.parameters.__dict__
            if self._state.parameters is not None
            else {}
        )
        request = ArkChatRequest(
            model=self._state.model,
            messages=messages,
            stream=stream,
            **parameters,
        )
        for hook in self.hooks:
            request = await hook(self._state, request)
        chat_request = request.get_chat_request()
        chat_request["context_id"] = self._state.context_id
        resp = await super().create(**chat_request)
        if not stream:
            ark_resp = ArkChatResponse.merge([resp])
            if resp.choices:
                self._state.messages.append(
                    convert_response_message(resp.choices[0].message)
                )
            return ark_resp
        else:

            async def iterator() -> AsyncIterable[ArkChatCompletionChunk]:
                chat_completion_messages = ChatCompletionMessage(
                    role="assistant",
                    content="",
                    tool_calls=[],
                )
                async for chunk in resp:
                    if len(chunk.choices) > 0:
                        if chunk.choices[0].delta.content:
                            chat_completion_messages.content += chunk.choices[
                                0
                            ].delta.content
                    yield ArkChatCompletionChunk(**chunk.__dict__)
                self._state.messages.append(
                    convert_response_message(chat_completion_messages)
                )

            return iterator()


class _AsyncContext(AsyncContext):
    def __init__(self, client: AsyncArk, state: State, hooks: List[ChatHook] = []):
        self._state = state
        self.hooks = hooks
        super().__init__(client)

    @property
    def completions(self) -> _AsyncCompletions:
        return _AsyncCompletions(self._client, self._state, self.hooks)
