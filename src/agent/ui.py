from rich.table import Table
from rich.console import Console
from agent.storage import queries
from dataclasses import dataclass
from agent.contracts import CompletionMetrics

# Terminal colors for output
YOU_COLOR = "\u001b[94m"  # Blue
ASSISTANT_COLOR = "\u001b[93m"  # Yellow
TOOL_COLOR = "\u001b[92m"  # Green
ERROR_COLOR = "\u001b[91m"  # Red
SUCCESS_COLOR = "\u001b[92m"  # Green
INFO_COLOR = "\u001b[96m"  # Cyan
RESET_COLOR = "\u001b[0m"

# Icons for better visual feedback
TOOL_ICON = "🔧"
FILE_ICON = "📄"
DIR_ICON = "📁"
SUCCESS_ICON = "✅"
ERROR_ICON = "❌"
THINKING_ICON = "🤔"

def display_sessions_dashboard(all_sessions: bool = False):
    convs = queries.get_all_conversations()
    if not convs:
        return None

    console = Console()
    title = "All Past Sessions" if all_sessions else "Recent Sessions"
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6, justify="center")
    table.add_column("Date / Time", width=20)
    table.add_column("Model", style="blue")
    table.add_column("Summary", style="green")
    table.add_column("Tokens", justify="right")
    table.add_column("Approx Cost", justify="right")
    table.add_column("Status", justify="center")

    sessions_to_show = convs if all_sessions else convs[:5]

    for c in sessions_to_show:
        status_style = "green" if c["status"] == "completed" else "yellow"
        cost_display = f"${c['approx_cost']:.6f}" if c["approx_cost"] else "$0.0000"
        summary = c["summary"] or "[No Summary Generated]"
        started_at = c["started_at"][:19] if c["started_at"] else "N/A"

        table.add_row(
            str(c["conversation_id"]),
            started_at,
            c["model"].split("/")[-1],
            summary,
            str(c["total_tokens"] or 0),
            cost_display,
            f"[{status_style}]{c['status']}[/{status_style}]"
        )

    console.print(table)
    return [c["conversation_id"] for c in convs]

def render_usage(metrics: CompletionMetrics, quiet: bool, show_ttft: bool, thinking_mode: bool)-> None:
    if metrics.duration_seconds > 0 and metrics.output_tokens and metrics.total_tokens > 0:
        duration = metrics.duration_seconds
        tps = metrics.output_tokens / metrics.duration_seconds
        if not quiet:
            if show_ttft:
                print(f"{INFO_COLOR}  [ {metrics.ttft_seconds:.1f}s - 1st token ]{RESET_COLOR}")
            if thinking_mode:
                print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {metrics.output_tokens} tokens in {duration:.2f}s | Thinking_Mode 🧠: ❌ ]{RESET_COLOR}\n")
            else:
                print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {metrics.output_tokens} tokens in {duration:.2f}s | Thinking_Mode 🧠 : ✅ ]{RESET_COLOR}\n")
