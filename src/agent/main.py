import os
import sys
from pathlib import Path

from agent.coding_agent import agent_loop
from agent.animation import print_banner
from dotenv import load_dotenv
from agent.ui import display_sessions_dashboard
from agent.authenticator import AuthenticationSession, Authenticator
import questionary

load_dotenv()

SUPPORTED_PROVIDERS = ("deepseek", "openrouter")

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


def ensure_config() -> tuple[str, str, str] | None:
    load_dotenv()
    provider = os.getenv("PROVIDER", "").strip().lower()
    model = os.getenv("MODEL", "").strip()
    api_key = os.getenv("API_KEY", "").strip()
    api_base = os.getenv("API_BASE", "").strip()

    if provider and model and api_key:
        return provider, model, api_key

    if not sys.stdin.isatty():
        # Avoid prompting for input when GlassBox is running non-interactively.
        print("Missing API configuration. Create a .env file or run GlassBox interactively to configure it.")
        return None

    print("GlassBox needs API configuration before first use.\n")

    if not provider:
        provider = questionary.select(
            "Select a provider:",
            choices=SUPPORTED_PROVIDERS,
            qmark="🤖",
        ).ask()
        if provider is None:
            return None

    if not api_key:
        api_key = (questionary.password(f"{provider} API key: ", qmark="🔑").ask() or "").strip()
        if not api_key:
            print("API key is required to start GlassBox.")
            return None

    selected_model_this_session = False
    if not model:
        authenticator = Authenticator(provider, "api_key")
        model_list = authenticator.fetch_models(api_key)
        if isinstance(model_list, str):
            print(model_list)
            return None

        model = questionary.select(
            "Select a model:",
            choices=model_list,
            qmark="🤖",
        ).ask()
        if model is None:
            return None
        selected_model_this_session = True

    save_model = True
    if selected_model_this_session:
        save_model = questionary.confirm(
            f"Use {model} as the default model?",
            default=True,
        ).ask()
        if save_model is None:
            return None

    if not api_base:
        api_base = input("API base URL (optional): ").strip()

    values = {"PROVIDER": provider, "API_KEY": api_key}
    if save_model:
        values["MODEL"] = model
    if api_base:
        values["API_BASE"] = api_base

    save_config = input("Save this configuration to .env? [Y/n]: ").strip().lower()
    if save_config in ("", "y", "yes"):
        _save_env_values(Path.cwd() / ".env", values)
        print("Configuration saved. Starting GlassBox...")
    else:
        print("Using configuration for this session only.")

    os.environ.update(values)

    return provider, model, api_key


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="GlassBox CLI — transparent coding assistant")
    group = parser.add_mutually_exclusive_group()
    
    group.add_argument("-r", "--resume", type=int, metavar="CONV_ID", help="Resume a conversation by its integer ID",)
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
    
    config = ensure_config()
    if config is None:
        return
    provider, model, api_key = config

    authenticator = Authenticator(provider, "api_key")
    session = authenticator.authenticate(model,api_key)

    if isinstance(session,AuthenticationSession):
        
        resume_id = None
        # resumptions logic
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

        agent_loop(session, 10, resume_id=resume_id)

    elif isinstance(session,str):
        print(f"{session}")

if __name__ == "__main__":
    main()
