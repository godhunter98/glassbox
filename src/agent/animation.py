import sys
import time
import threading

# Colors
CYAN    = "\u001b[96m"
GREEN   = "\u001b[92m"
YELLOW  = "\u001b[93m"
DIM     = "\u001b[2m"
BOLD    = "\u001b[1m"
RESET   = "\u001b[0m"

BANNER_LINES = [
    r"  ██████╗ ██████╗ ██████╗ ██╗███╗   ██╗ ██████╗      █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    r" ██╔════╝██╔═══██╗██╔══██╗██║████╗  ██║██╔════╝     ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    r" ██║     ██║   ██║██║  ██║██║██╔██╗ ██║██║  ███╗    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
    r" ██║     ██║   ██║██║  ██║██║██║╚██╗██║██║   ██║    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
    r" ╚██████╗╚██████╔╝██████╔╝██║██║ ╚████║╚██████╔╝    ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
    r"  ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
]

TAGLINE  = "🤖 Your provider-agnostic coding assistant"
DIVIDER  = "─" * 80
TOOLS_LINE = "  🔧 read  ·  📁 list  ·  ✏️  edit  ·  💻 bash  ·  📜 script"


def print_banner():
    print()
    for i, line in enumerate(BANNER_LINES):
        color = CYAN if i % 2 == 0 else GREEN
        print(f"{BOLD}{color}{line}{RESET}")
    print()
    print(f"{YELLOW}{BOLD}  {TAGLINE}{RESET}")
    print(f"{DIM}{CYAN}  {DIVIDER}{RESET}")
    print(f"{DIM}{TOOLS_LINE}{RESET}")
    print(f"{DIM}{CYAN}  {DIVIDER}{RESET}")
    print()


class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Assistant is thinking..."):
        self.message = message
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        i = 0
        while not self._stop_event.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{CYAN}{frame}{RESET} {DIM}{self.message}{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def _clear(self):
        sys.stdout.write("\r" + " " * (len(self.message) + 4) + "\r")
        sys.stdout.flush()

    def start(self):
        print()  # blank line above the spinner
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join()
        self._clear()
