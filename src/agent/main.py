import os
from agent.coding_agent import agent_loop
from agent.animation import print_banner
from dotenv import load_dotenv

load_dotenv()

model = os.getenv("MODEL", "")
api_key = os.getenv("API_KEY", "")


def main():
    print_banner()
    agent_loop(model, api_key,10)


if __name__ == "__main__":
    main()
