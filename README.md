# GlassBox 🔍

A transparent, provider-agnostic CLI coding assistant powered by LLMs via [litellm](https://github.com/BerriAI/litellm).

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/7e874f02-f69b-4045-8ba3-351b3c38aaac" />

## Features

- 5 tools: read, list, edit files · run bash commands · run bash scripts
- Built on LiteLLM, with DeepSeek-oriented tool schema support and optional local API base URL
- Safety checks on shell commands with warn + confirm prompt
- Animated terminal UI — block-letter banner, braille spinner
- Conversation persistence with session listing and resume support
- Pytest coverage for tools, CLI routing, and resume reconstruction

## Installation

```bash
git clone <repository-url>
cd glassbox
uv sync
```

Or with pip: `pip install -e .`

## Configuration

Create a `.env` file:

```env
MODEL="deepseek/deepseek-coder"
API_KEY="your-api-key-here"
API_BASE="http://localhost:8000/v1"  # optional, for local models
```

Any model supported by litellm works.

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
```

Inside a session, type `exit`, `quit`, or press `Ctrl+C` to quit.

## Project structure

```
glassbox/
├── src/
│   └── agent/
│       ├── main.py              # CLI entrypoint and session selection
│       ├── coding_agent.py      # agent loop, LLM calls, tool execution
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

- Missing env vars → set `MODEL` and `API_KEY` in `.env`
- LLM call fails → check API key, model name, and network
- File errors → verify path and permissions
- `python main.py` fails → use `agent` or `python -m agent.main`; the entrypoint lives under `src/agent/`
