import os
from agent.coding_agent import agent_loop
from agent.animation import print_banner
from dotenv import load_dotenv
from agent.ui import display_sessions_dashboard

load_dotenv()

model = os.getenv("MODEL", "")
api_key = os.getenv("API_KEY", "")


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

    agent_loop(model, api_key, 10, resume_id=resume_id)


if __name__ == "__main__":
    main()

