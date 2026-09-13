
from agent.providers.openai_codex.codex_auth import fetch_credentials_for_request
import requests
import jwt
import json

CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

# client = httpx.Client()

class CodexRequest:
    '''Serve requests using the openAI codex auth'''
     
    def __init__(self, model: str = "gpt-5.5") -> None:
        self.model = model
    
    def _get_credentials(self):
        self.auth_token = fetch_credentials_for_request()
        self.access_token = self.auth_token.get("access_token")
        self.id_token = self.auth_token.get("id_token")
        if not self.id_token or not self.access_token:
            raise RuntimeError("Missing Codex authentication tokens")
    
    def generate_response(self, user_input: str):
        
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
        payload = {
        "model": self.model,  # Replace with your intended Codex-supported model
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_input.strip(),
                    }
                ],
            }
        ],
        "stream": True, #codex backend does not allow us to use non-streaming responses
        "store":False 
        }
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

            event = json.loads(data)

            if event.get("type") == "response.output_item.done" and event.get("item",{}).get("phase")=="final_answer":
                final_text = event["item"]["content"][0]["text"]

        return final_text