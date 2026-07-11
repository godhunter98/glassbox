import os
import sys
from getpass import getpass
from pathlib import Path
from agent.coding_agent import agent_loop
from agent.animation import print_banner
from dotenv import load_dotenv
from agent.ui import display_sessions_dashboard

load_dotenv()

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def _quote_env_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _save_env_values(env_path: Path, values: dict[str, str]) -> None:
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated_lines = []
    seen_keys = set()

    for line in existing_lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped and not stripped.startswith("#") else None
        if key in values:
            updated_lines.append(f"{key}={_quote_env_value(values[key])}")
            seen_keys.add(key)
        else:
            updated_lines.append(line)

    for key, value in values.items():
        if key not in seen_keys and value:
            updated_lines.append(f"{key}={_quote_env_value(value)}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def ensure_config() -> tuple[str, str] | None:
    load_dotenv()
    model = os.getenv("MODEL", "").strip()
    api_key = os.getenv("API_KEY", "").strip()
    api_base = os.getenv("API_BASE", "").strip()

    if model and api_key:
        return model, api_key

    if not sys.stdin.isatty():
        print("Missing MODEL/API_KEY. Create a .env file or run GlassBox interactively to configure it.")
        return None

    print("GlassBox needs API configuration before first use.\n")

    if not model:
        model_input = input(f"Model [{DEFAULT_MODEL}]: ").strip()
        model = model_input or DEFAULT_MODEL

    if not api_key:
        api_key = getpass("API key: ").strip()
        if not api_key:
            print("API key is required to start GlassBox.")
            return None

    if not api_base:
        api_base = input("API base URL (optional): ").strip()

    save_config = input("Save this configuration to .env? [Y/n]: ").strip().lower()
    values = {"MODEL": model, "API_KEY": api_key}
    if api_base:
        values["API_BASE"] = api_base

    if save_config in ("", "y", "yes"):
        _save_env_values(Path.cwd() / ".env", values)
        print("Configuration saved. Starting GlassBox...")
    else:
        print("Using configuration for this session only.")

    os.environ.update(values)
    return model, api_key


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="GlassBox CLI — transparent coding assistant")
    group = parser.add_mutually_exclusive_group()
    
    group.add_argument("-r", "--resume", type=int, help="Resume conversation by ID")
    group.add_argument("-l", "--list", action="store_true", help="List all past conversations")
    group.add_argument("-n", "--new", action="store_true", help="Start a new session directly")
    
    return parser.parse_args()



def main():
    print_banner()
    args = parse_args()
    
    if args.list:
        available_ids = display_sessions_dashboard(all_sessions=True)
        if not available_ids:
            print("No past sessions found.")
        return
        
    resume_id = None
    if args.resume is not None:
        resume_id = args.resume
    elif not args.new:
        available_ids = display_sessions_dashboard(all_sessions=False)
        if available_ids:
            try:
                user_input = input("\nEnter session ID to resume, or press Enter to start a new session: ").strip()
                if user_input:
                    if user_input.lower() in ["n", "new"]:
                        resume_id = None
                    else:
                        try:
                            selected_id = int(user_input)
                            if selected_id in available_ids:
                                resume_id = selected_id
                            else:
                                print(f"Invalid ID '{selected_id}'. Starting a new session instead.")
                                resume_id = None
                        except ValueError:
                            print(f"Invalid input '{user_input}'. Starting a new session instead.")
                            resume_id = None
                else:
                    resume_id = None
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye! 👋")
                return
        else:
            resume_id = None

    config = ensure_config()
    if config is None:
        return
    model, api_key = config

    agent_loop(model, api_key, 10, resume_id=resume_id)


if __name__ == "__main__":
    main()
