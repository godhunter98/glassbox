# GlassBox 🔍

A local, transparent CLI coding assistant powered by LLMs via [LiteLLM](https://github.com/BerriAI/litellm).

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/7e874f02-f69b-4045-8ba3-351b3c38aaac" />

## Features

- 5 tools: read, list, edit files · run bash commands · run bash scripts
- Provider setup for DeepSeek and OpenRouter, with model discovery and API-key validation
- Saved local configuration for provider, model, API key, and optional API base URL
- Slash commands with autocomplete: `/help`, `/config`, and `/exit`
- Safety checks on shell commands with warn + confirm prompt
- Animated terminal UI — block-letter banner, braille spinner
- Conversation persistence with session listing and resume support
- Fast CLI startup: provider and agent dependencies load only when needed
- Pytest coverage for tools, CLI routing, and resume reconstruction

## Installation

```bash
git clone <repository-url>
cd glassbox
uv sync
```

Or with pip: `pip install -e .`

## Configuration

Run interactive setup:

```bash
agent --configure
```

GlassBox lets you choose DeepSeek or OpenRouter, enter an API key, fetch the
available models, and optionally save the result to `.env`.

You can also create `.env` manually:

```env
PROVIDER="deepseek"
MODEL="deepseek/deepseek-v4-flash"
API_KEY="your-api-key-here"
API_BASE="http://localhost:8000/v1"  # optional, for local models
```

If configuration is incomplete, GlassBox starts the same interactive setup on
the next run. Saved credentials are used immediately; they are validated when
you configure them and again naturally on the first model request.

## Usage

```bash
uv run agent
# or
agent
# or, from the source tree
uv run python -m agent.main
```

Useful options:

```bash
agent -n          # start a new session
agent -l          # list past sessions
agent -r 3        # resume conversation ID 3
agent -c          # configure provider, API key, and model
```

Inside a session, use:

```text
/help             # show available commands
/config           # show configuration guidance
/exit             # save and exit
```

Command suggestions appear after typing `/`. You can also type `exit` or press
`Ctrl+C` to leave the session.

## Project structure

```
glassbox/
├── src/
│   └── agent/
│       ├── main.py              # CLI entrypoint and session selection
│       ├── coding_agent.py      # agent loop, LLM calls, tool execution
│       ├── authenticator.py     # provider credentials and model discovery
│       ├── config_manager.py    # interactive setup and .env persistence
│       ├── command_runner.py    # local slash-command handling
│       ├── tools.py             # tool implementations and schemas
│       ├── context_manager.py   # context truncation and session state
│       ├── prompts.py           # system prompt
│       ├── animation.py         # banner and spinner
│       ├── ui.py                # colors, icons, session dashboard
│       └── storage/
│           ├── db.py            # SQLite schema setup
│           └── queries.py       # persistence helpers
├── tests/                       # pytest suite
├── pyproject.toml
└── uv.lock
```

## Adding new tools

1. Add a typed function in `src/agent/tools.py`.
2. Decorate it with `@register_tool`.
3. Give it a clear docstring. The decorator uses the function name, type hints, and docstring to build the tool schema.
4. Add or update tests in `tests/`.

## Testing

```bash
uv run pytest
```

If you already have the local virtual environment set up:

```bash
.venv/bin/python -m pytest -q
```

## Troubleshooting

- Missing configuration → run `agent --configure`
- LLM call fails → check API key, model name, and network
- Provider model list fails → check your API key and provider network access
- File errors → verify path and permissions
- `python main.py` fails → use `agent` or `python -m agent.main`; the entrypoint lives under `src/agent/`
