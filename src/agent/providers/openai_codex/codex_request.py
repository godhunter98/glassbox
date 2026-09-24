import json
import time
from typing import Any

import jwt
import requests

from agent.contracts import CompletionMetrics, CompletionResult
from agent.providers.openai_codex.codex_auth import fetch_credentials_for_request


CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
MAX_ATTEMPTS = 3


class CodexRequest:
    """Send authenticated streaming requests to the ChatGPT Codex backend."""

    CodexInput = dict[str, str | list[dict[str, Any]]]

    def __init__(self, model: str = "gpt-5.5") -> None:
        self.model = model

    def _get_credentials(self) -> None:
        credentials = fetch_credentials_for_request()
        self.access_token = credentials.get("access_token")
        self.id_token = credentials.get("id_token")
        if not isinstance(self.access_token, str) or not isinstance(self.id_token, str):
            raise RuntimeError("Missing Codex authentication tokens")

    @staticmethod
    def _failure_result(message: str, error: Exception, started_at: float) -> CompletionResult:
        duration = time.perf_counter() - started_at
        return CompletionResult(
            response=message,
            metrics=CompletionMetrics(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                ttft_seconds=duration,
                duration_seconds=duration,
            ),
            error=error,
        )

    @staticmethod
    def conversation_to_codex_input(
        conversation: list[dict[str, Any]],
    ) -> CodexInput:
        """Convert GlassBox text messages into Codex Responses input items."""
        system_messages: list[str] = []
        input_messages: list[dict[str, Any]] = []

        for message in conversation:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str) or not content:
                continue

            if role == "system":
                system_messages.append(content)
            elif role == "user":
                input_messages.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
            elif role == "assistant":
                input_messages.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": content,
                                "annotations": [],
                            }
                        ],
                        "status": "completed",
                    }
                )

        return {
            "system": "\n\n".join(system_messages),
            "input": input_messages,
        }

    def _build_payload(self, converted_conversation: CodexInput) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "store": False,
            "input": converted_conversation["input"],
        }
        if converted_conversation["system"]:
            payload["instructions"] = converted_conversation["system"]
        return payload

    def generate_response(self, conversation: list[dict[str, Any]]) -> CompletionResult:
        """Return text and metrics from a Codex SSE response."""
        request_started_at = time.perf_counter()
        try:
            self._get_credentials()
            claims = jwt.decode(self.id_token, options={"verify_signature": False})
            account_id = claims["https://api.openai.com/auth"]["chatgpt_account_id"]
        except (jwt.PyJWTError, KeyError, TypeError, RuntimeError) as error:
            return self._failure_result(
                f"Could not prepare Codex request: {error}", error, request_started_at
            )

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "ChatGPT-Account-Id": account_id,
            "originator": "GlassBox",
            "User-Agent": "Glassbox/0.1.0",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = self._build_payload(self.conversation_to_codex_input(conversation))

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    CODEX_ENDPOINT,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=60,
                )
                response.raise_for_status()
                response.encoding = "utf-8"
                break
            except requests.exceptions.RequestException as error:
                if isinstance(
                    error,
                    (requests.exceptions.Timeout, requests.exceptions.ConnectionError),
                ):
                    retryable = True
                elif isinstance(error, requests.exceptions.HTTPError):
                    status_code = error.response.status_code if error.response is not None else None
                    retryable = status_code == 429 or (
                        status_code is not None and 500 <= status_code < 600
                    )
                else:
                    retryable = False

                if not retryable or attempt == MAX_ATTEMPTS:
                    return self._failure_result(
                        f"Could not generate response due to {error}",
                        error,
                        request_started_at,
                    )
                time.sleep(2 ** (attempt - 1))

        final_text = ""
        input_tokens = output_tokens = total_tokens = 0
        first_text_at: float | None = None
        completed = False

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line.startswith("data: "):
                    continue

                data = line.removeprefix("data: ")
                if data == "[DONE]":
                    break

                event = json.loads(data)
                event_type = event.get("type")

                if event_type == "response.output_text.delta" and event.get("delta"):
                    if first_text_at is None:
                        first_text_at = time.perf_counter()
                elif event_type == "response.output_item.done":
                    item = event.get("item", {})
                    content = item.get("content", [])
                    if item.get("phase") == "final_answer" and content:
                        final_text = content[0].get("text", "")
                elif event_type == "response.completed":
                    completed_response = event.get("response", {})
                    if completed_response.get("status") != "completed":
                        error = RuntimeError("Codex response did not complete successfully")
                        return self._failure_result(str(error), error, request_started_at)

                    usage = completed_response.get("usage") or {}
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    total_tokens = usage.get("total_tokens", 0)
                    completed = True
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, TypeError) as error:
            return self._failure_result(
                f"Could not read Codex response: {error}", error, request_started_at
            )

        if not completed:
            error = RuntimeError("Codex stream ended without response.completed")
            return self._failure_result(str(error), error, request_started_at)

        finished_at = time.perf_counter()
        ttft = (
            first_text_at - request_started_at
            if first_text_at is not None
            else finished_at - request_started_at
        )
        generation_duration = (
            finished_at - first_text_at
            if first_text_at is not None
            else finished_at - request_started_at
        )
        return CompletionResult(
            response=final_text,
            metrics=CompletionMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                ttft_seconds=ttft,
                duration_seconds=generation_duration,
            ),
        )

    def __repr__(self) -> str:
        return f"<CodexRequest(model={self.model!r}) at {hex(id(self))}>"
