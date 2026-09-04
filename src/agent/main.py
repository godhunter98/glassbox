from agent.animation import print_banner
from agent.config_manager import ConfigManager
from agent.ui import display_sessions_dashboard


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="GlassBox CLI — transparent coding assistant")
    group = parser.add_mutually_exclusive_group()
    
    group.add_argument("-r", "--resume", type=int, metavar="CONV_ID", help="Resume a conversation by its integer ID",)
    group.add_argument("-l", "--list", action="store_true", help="List all past conversations")
    group.add_argument("-n", "--new", action="store_true", help="Start a new session directly")
    group.add_argument("-c", "--configure", action="store_true", help="Configure a provider, API key, and model")
    
    return parser.parse_args()



def main():
    print_banner()
    args = parse_args()

    if args.list:
        available_ids = display_sessions_dashboard(all_sessions=True)
        if not available_ids:
            print("No past sessions found.")
        return

    config_manager = ConfigManager()
    if args.configure:
        config_manager.configure()
        return

    session = config_manager.get_session()
    if session is None:
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
                    if user_input.lower() not in ["n", "new"]:
                        try:
                            selected_id = int(user_input)
                            if selected_id in available_ids:
                                resume_id = selected_id
                            else:
                                print(f"Invalid ID '{selected_id}'. Starting a new session instead.")
                        except ValueError:
                            print(f"Invalid input '{user_input}'. Starting a new session instead.")

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye! 👋")
                return

    from agent.coding_agent import agent_loop

    agent_loop(session, 10, resume_id=resume_id)

if __name__ == "__main__":
    main()
