
from agent.providers.openai_codex.codex_auth import fetch_credentials_for_request
import requests
import jwt
import json
from typing import Any

CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

# client = httpx.Client()

class CodexRequest:
    '''Serve requests using the openAI codex auth'''

    CodexInput = dict[str, str | list[dict[str, Any]] | None]

    def __init__(self, model: str = "gpt-5.5") -> None:
        self.model = model

    def _get_credentials(self):
        self.auth_token = fetch_credentials_for_request()
        self.access_token = self.auth_token.get("access_token")
        self.id_token = self.auth_token.get("id_token")
        if not self.id_token or not self.access_token:
            raise RuntimeError("Missing Codex authentication tokens")

    @staticmethod
    def conversation_to_codex_input(
        conversation: list[dict[str, str]]
    ) -> CodexInput:
        system_messages = ""
        input_messages = []
        tools = []
        for message in conversation:
            content = message.get("content")
            role = message.get("role")
            if role and content:
                if role == "system":
                    system_messages+=content
                elif role == "user":
                    input_messages.append(
                        {"role": role,
                        "content": [
                                {"type": "input_text", "text": content}
                            ]
                        })
                elif role == "assistant":
                    input_messages.append(
                        {"type": "message",
                        "role": "assistant",
                        "content": [
                                {"type": "output_text", "text": content}
                            ],
                        "status": "completed",
                        })
                elif role == "tool":
                    tools.append(content)
        return {
            "system": system_messages,
            "input": input_messages,
            "tool": None,
        }

    def _build_payload(self, converted_conversation: CodexInput) -> dict:
        payload = {
            "model": self.model,
            "stream": True, #codex backend does not allow us to use non-streaming responses
            "store": False,
        }
        payload["instructions"] = converted_conversation.get("system")
        payload["input"] = converted_conversation.get("input")
        return payload

    def generate_response(self, conversation: list[dict[str,str]]) -> str:
        self._get_credentials()

        if isinstance(self.id_token,str):
            claims = jwt.decode(
                self.id_token,
                options={"verify_signature": False}
            )
        self.user_name = claims["name"]
        self.chatgpt_account_id = claims["https://api.openai.com/auth"]["chatgpt_account_id"]

        headers = {
            "Authorization":f"Bearer {self.access_token}",
            "ChatGPT-Account-Id":self.chatgpt_account_id,
            "originator":"GlassBox",
            "User-Agent":"Glassbox/0.1.0",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        payload = self._build_payload(self.conversation_to_codex_input(conversation))

        response = requests.post(
            CODEX_ENDPOINT,
            headers=headers,
            json=payload,
            stream=True,
            timeout=60,
        )
        response.raise_for_status()
        response.encoding = "utf-8"

        final_text = ""
        for line in response.iter_lines(decode_unicode=True):
            if not line.startswith("data: "):
                continue

            data = line.removeprefix("data: ")
            if data == "[DONE]":
                break

            try:
                event = json.loads(data)

                if event.get("type") == "response.output_item.done" and event.get("item",{}).get("phase")=="final_answer":
                    final_text = event["item"]["content"][0]["text"]

            except (json.JSONDecodeError, KeyError) as e:
                final_text = f"Could not generate response due to {e}"

        return final_text

    def __repr__(self) -> str:
        return f"<CodexRequest(model={self.model!r}) at {hex(id(self))}>"
