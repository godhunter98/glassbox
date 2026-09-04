"""Local command handling for the interactive agent prompt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    handled: bool
    should_exit: bool = False
    message: str | None = None


class CommandRunner:
    """Recognize and handle commands without sending them to the LLM."""

    HELP_TEXT = "Available commands: /help, /exit, /config"

    def run(self, user_input: str) -> CommandResult:
        command = user_input.strip().lower()

        if command in {"exit", "quit", "/exit"}:
            return CommandResult(handled=True, should_exit=True)

        if command == "/help":
            return CommandResult(handled=True, message=self.HELP_TEXT)

        if command == "/config":
            return CommandResult(
                handled=True,
                message="Run `agent --configure` before starting a conversation to change configuration.",
            )

        if command.startswith("/"):
            return CommandResult(handled=True, message=f"Unknown command: {command}. Type /help for help.")

        return CommandResult(handled=False)
