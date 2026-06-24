import json
import os
import warnings
import time
import logging
from typing import Any, Dict, List
from litellm import litellm
import json
from rich.live import Live
from rich.markdown import Markdown
from rich import print as rprint
from agent.storage import queries
from agent.tools import (
    get_tool_schema,
    tool_registry
)
from agent.prompts import SYSTEM_PROMPT
from agent.animation import Spinner
from agent.ui import (
    YOU_COLOR,
    ASSISTANT_COLOR,
    TOOL_COLOR,
    ERROR_COLOR,
    SUCCESS_COLOR,
    INFO_COLOR,
    RESET_COLOR,
    TOOL_ICON,
    SUCCESS_ICON,
    ERROR_ICON,
)
from agent.context_manager import truncate_tool_output, mask_old_observations, Session_state

DEEPSEEK_MAX_CONTEXT = 1_000_000
EXPECTED_MAX_OUTPUT  = 384_000
SLACK                = 50_000        # one turn's growth between measure and act
CONTEXT_LIMIT = DEEPSEEK_MAX_CONTEXT - EXPECTED_MAX_OUTPUT - SLACK
STATE_INJECT_GROWTH = 3_000   # re-inject after this much prompt-token growth; tune later

# Temp variables to test functionality
CONTEXT_LIMIT = 6_000
STATE_INJECT_GROWTH = 3_000

# Disable pydantic warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
os.environ["LITELLM_IGNORE_PYDANTIC_WARNINGS"] = "1"

# Silence litellm logs
logging.getLogger("litellm").setLevel(logging.WARNING)
os.environ["LITELLM_LOG"] = "ERROR"


llm_config = {}


if os.environ.get("API_BASE"):
    llm_config["api_base"] = os.environ["API_BASE"]


def build_messages(conversation: List[Dict[str, str]]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    for msg in conversation:
        if msg["role"] == "system":
            messages.append({"role": "system", "content": msg["content"]})
        else:
            messages.append(msg)
    return messages


def load_conversation(conversation_id: int) -> List[Dict[str, Any]]:
    # Start with the standard system prompt
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Retrieve all user & assistant messages, ordered chronologically
    db_messages = queries.get_conversation_messages(conversation_id)
    
    for msg in db_messages:
        role = msg["role"]
        
        if role == "user":
            conversation.append({"role": "user", "content": msg["content"]})
            
        elif role == "assistant":
            # Fetch any tool calls associated with this assistant message
            tool_calls = queries.get_tool_calls_for_message(msg["message_id"])
            
            if not tool_calls:
                conversation.append({"role": "assistant", "content": msg["content"]})
            else:
                # 1. Reconstruct the tool_calls property for the assistant message
                tc_list = []
                tool_msgs = []
                
                for tc in tool_calls:
                    call_id = f"call_{tc['tool_id']}"
                    
                    tc_list.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tc["tool_name"],
                            "arguments": tc["tool_args"]
                        }
                    })
                    
                    # 2. Prepare the matching 'tool' role message
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tc["tool_name"],
                        "content": truncate_tool_output(tc["tool_output"],tc["tool_name"])
                    })
                
                conversation.append({
                    "role": "assistant",
                    "content": msg["content"],
                    "tool_calls": tc_list
                })
                conversation.extend(tool_msgs)
                
    return conversation


def print_conversation_history(conversation: List[Dict[str, Any]]):
    print(f"\n{INFO_COLOR}=== Resuming Conversation History ==={RESET_COLOR}")
    
    i = 0
    while i < len(conversation):
        msg = conversation[i]
        role = msg["role"]
        
        if role == "system":
            i += 1
            continue
            
        if role == "user":
            print(f"\n{YOU_COLOR}You:{RESET_COLOR} {msg['content']}")
            i += 1
            continue
            
        if role == "assistant":
            print(f"\n{ASSISTANT_COLOR}Assistant:{RESET_COLOR}")
            if msg.get("content"):
                rprint(Markdown(msg["content"]))
                
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                print(f"{TOOL_COLOR}🔄 Executed {len(tool_calls)} tool{'s' if len(tool_calls) > 1 else ''}...{RESET_COLOR}")
                for idx, tc in enumerate(tool_calls, 1):
                    func = tc["function"]
                    try:
                        args = json.loads(func["arguments"])
                        args_display = ", ".join(f"{k}={v}" for k, v in args.items())
                      # Check if args is a dict/string or something else
                    except Exception:
                        args_display = func["arguments"]
                    print(f"  {idx}. {TOOL_ICON} {func['name']}({args_display})")
                    
                    # Find matching tool response to print success/error indicator
                    for j in range(i + 1, len(conversation)):
                        candidate = conversation[j]
                        if candidate["role"] == "tool" and candidate.get("tool_call_id") == tc["id"]:
                            try:
                                resp_data = json.loads(candidate["content"])
                                if isinstance(resp_data, dict) and "error" in resp_data:
                                    print(f"     {ERROR_ICON} {ERROR_COLOR}Error: {resp_data['error']}{RESET_COLOR}")
                                else:
                                    print(f"     {SUCCESS_ICON} {SUCCESS_COLOR}Success{RESET_COLOR}")
                            except Exception:
                                print(f"     {SUCCESS_ICON} {SUCCESS_COLOR}Success{RESET_COLOR}")
                            break
            i += 1
            continue
            
        if role == "tool":
            # Tool responses are inline under the assistant message, so we skip them here
            i += 1
            continue
            
    print(f"\n{INFO_COLOR}======================================{RESET_COLOR}\n")


def print_error(context: str, message: str) -> None:
    print(f"{ERROR_COLOR}{ERROR_ICON} {context}: {message}{RESET_COLOR}")


def llm_completions(conversation: List[Dict[str, str]], model: str, api_key: str,spinner:Spinner=None,show_ttft=True):
    
    messages = build_messages(conversation)
    if model and api_key is not None:
        kwargs = {
            "model": model,
            "api_key": api_key,
            "messages": messages,
            "max_tokens": 20_000,
            "temperature": 0.1,
            "tools": get_tool_schema(model),
            "stream":True,
            "extra_body":{"thinking": {"type": "disabled"}}
        }

        # Allow overriding the LLM base URL without changing call sites.
        if llm_config.get("api_base"):
            kwargs["api_base"] = llm_config["api_base"]
            
        for attempt in range(3):
            try:
                response = litellm.completion(**kwargs)
                chunks = []

                request_time = time.perf_counter()
                start_time = None

                # Stop spinner before Live takes over the terminal
                if spinner:
                    spinner.stop()
                    spinner = None

                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR}")
                accumulated_text = ""
                with Live("", refresh_per_second=15, vertical_overflow="visible") as live:
                    for chunk in response:
                        if start_time is None:
                            start_time = time.perf_counter()
                            ttft = start_time - request_time
                        delta = chunk.choices[0].delta
                        if delta.content:
                            accumulated_text += delta.content
                            live.update(Markdown(accumulated_text))
                        chunks.append(chunk)

                end_time = time.perf_counter()

                full_response = litellm.stream_chunk_builder(chunks)
                usage = getattr(full_response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                completion_tokens = getattr(usage, "completion_tokens", None)
                total_tokens = getattr(usage, "total_tokens", None)

                if prompt_tokens is not None:
                    print(f"{INFO_COLOR}  [ {prompt_tokens} toks / {DEEPSEEK_MAX_CONTEXT} ]{RESET_COLOR}")

                if start_time is not None and completion_tokens and completion_tokens > 0:
                    duration = end_time - start_time
                    tps = completion_tokens / duration
                    if show_ttft:
                        print(f"{INFO_COLOR}  [ {ttft:.1f}s - 1st token ]{RESET_COLOR}")
                    if kwargs.get("extra_body", {}).get("thinking") == {"type": "disabled"}:
                        print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {completion_tokens} tokens in {duration:.2f}s | Thinking_Mode 🧠: ❌ ]{RESET_COLOR}\n")
                    else:
                        print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {completion_tokens} tokens in {duration:.2f}s | Thinking_Mode 🧠 : ✅ ]{RESET_COLOR}\n")

                return full_response, prompt_tokens, total_tokens
                
            except Exception as e:
                last_error = e
                delay = 2**attempt
                print(f"Attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                time.sleep(delay)

        error_msg = f"LLM call failed: {str(last_error)}"
        print_error("LLM error", error_msg)
        print(
            f"{INFO_COLOR}Make sure you have set up your API keys in the .env file{RESET_COLOR}"
        )
        print(f"{INFO_COLOR}Current model: {model}{RESET_COLOR}")
        return f"I encountered an error: {error_msg}. Please check your API key configuration.",0
    
    else:
        error_msg = "Missing environment variable: MODEL or API_KEY"
        print_error("Configuration error", error_msg)
        print(
            f"{INFO_COLOR}Please set MODEL and API_KEY in your .env file{RESET_COLOR}"
        )
        return f"I encountered an error: {error_msg}. Please check your .env file configuration.",0


def run_tool_call(
    tool_call, conversation: List[Dict[str, Any]], index: int , db_msg_id: int, session_state:Session_state
) -> None:
    tool_name = tool_call.function.name
    try:
        # Tool arguments arrive as JSON strings in the model response.
        tool_args = json.loads(tool_call.function.arguments)
        args_display = ", ".join(f"{k}={v}" for k, v in tool_args.items())
        print(f"  {index}. {TOOL_ICON} {tool_name}({args_display})")

        tool = tool_registry.get(tool_name)
        
        # error handling if tool doesn't exist
        if not tool:
            error_msg = f"Unknown tool: {tool_name}"
            print_error("Tool error", error_msg)
            conversation.append(
                {
                    "role": "tool",
                    "name":tool_name,
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": error_msg}),
                }
            )
            return

        try:
            resp = tool(**tool_args)
            
            if tool_name in {"read_file","edit_file"}:
                # Track file touches for file-related tools
                path = tool_args.get("path") or tool_args.get("filename")
                if path:
                    session_state.record_file(path)
                
            # tool args and tool resp are dicts, but sqlite needs a string, we dump them!
            queries.add_tool_call(db_msg_id,tool_name,json.dumps(tool_args),json.dumps(resp))
            resp_str = truncate_tool_output(json.dumps(resp),tool_name)
            conversation.append(
                {
                    "role": "tool",
                    "name":tool_name,
                    "tool_call_id": tool_call.id,
                    "content": resp_str,
                }
            )
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            print_error("Tool error", error_msg)
            session_state.record_blocker(tool_name,tool_args,error_msg)
            conversation.append(
                {
                    "role": "tool",
                    "name":tool_name,
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": error_msg}),
                }
            )

    except json.JSONDecodeError:
        print("The model sent back a broken JSON string!")

def handle_assistant_message(assistant_message, conversation: List[Dict[str, Any]],conversation_id: int,session_state:Session_state) -> None:
    content = getattr(assistant_message, "content", "") or ""
    tool_calls = getattr(assistant_message, "tool_calls", None) or []
    # Capture reasoning_content if present (DeepSeek thinking mode)
    reasoning_content = getattr(assistant_message, "reasoning_content", None)

    db_msg_id = queries.add_message(conversation_id,"assistant",content)

    if not tool_calls:
        msg = ({"role": "assistant", "content": content})
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        conversation.append(msg)
        return 

    # Preserve the model's assistant message before executing any tool calls.
    msg = {
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls,
    }
    
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    conversation.append(msg)

    print(
        f"{TOOL_COLOR}🔄 Executing {len(tool_calls)} tool{'s' if len(tool_calls) > 1 else ''}...{RESET_COLOR}"
    )

    for index, tool_call in enumerate(tool_calls, 1):
        run_tool_call(tool_call, conversation, index, db_msg_id, session_state)



def generate_conversation_summary(conversation: List[Dict[str,Any]],model:str,api_key:str) -> str:
    '''Generate a summary from the completed conversation.'''
    print(f"\n{INFO_COLOR}Saving conversation...{RESET_COLOR}")
    
    # Build a lightweight summary request — only the conversation content matters,
    # not the original system prompt, so we replace it with a summary-specific one.
    summary_messages = [
        {
            "role": "system",
            "content": (
                "You generate concise session titles. "
                "Focus on the MAIN TASK or TOPIC the user worked on. "
                "Use 4 to 8 words. No punctuation. No quotes. No extra text.\n\n"
                "NEVER use generic phrases like 'session ended', 'user asked', 'discussion about', or 'before discussion'. "
                "Always describe the specific topic even if the conversation was short or casual."
            ),
        },
    ]

    # Include only user and assistant text content (skip tool messages to save tokens)
    for msg in conversation:
        if msg["role"] in ("user", "assistant") and msg.get("content"):
            summary_messages.append({"role": msg["role"], "content": msg["content"]})

    summary_messages.append({
        "role": "user",
        "content": (
            "Generate a title for this session.\n\n"
            "Good titles:\n"
            "- Debug Flask login route 500 error\n"
            "- Add pagination to REST API\n"
            "- Refactor database connection pooling\n"
            "- Casual chat about coding projects\n"
            "- Explored project structure and dependencies\n\n"
            "Bad titles (NEVER use these patterns):\n"
            "- Session ended before discussion\n"
            "- User asked about X then ended chat\n\n"
            "Title:"
        ),
    })

    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": summary_messages,
        "max_tokens": 30,
        "temperature": 0.3,
        "stream": False,
        "extra_body":{"thinking": {"type": "disabled"}}
    }

    if llm_config.get("api_base"):
        kwargs["api_base"] = llm_config["api_base"]

    try:
        for attempt in range(2):
            response = litellm.completion(**kwargs)
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()
        return "Untitled session"
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Summary could not be generated."

def refresh_session_state(
    conversation: List[Dict],
    model: str,
    api_key: str,
    session_state: Session_state,
) -> bool:
    instruction = [
        {
            "role": "system",
            "content": (
                '''You're a specialised agent who's job is to look at the conversation between a user
                and an agent and generate structured JSON in the below format.
                {"goal":"...",
                "next_steps":[],
                "decisions":[]
                }
                The conversation may contain tool calls and their results or past session state objects as well, 
                your job is to absorb everything and generate the above mentioned dict with 3 items.
                '''
            ),
        },
    ]
    messages = instruction + [{
    "role":msg["role"], "content":msg["content"]}
    for msg in conversation
    if msg["role"] in ("user","assistant") and msg.get("content")
    ]
    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": messages,
        "max_tokens": 2_000,
        "temperature": 0.2,
        "stream": False,
        "response_format":{"type": "json_object"} ,
        "extra_body":{"thinking": {"type": "disabled"}}
    }

    
    try:
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        if not content:                       # DeepSeek empty-content case
            return False
        
        try:
            state_dict = json.loads(content)
        except json.JSONDecodeError:
            return False

        session_state.refresh_reasoning(
                goal=state_dict.get("goal", session_state.goal),
                decisions=state_dict.get("decisions", []),
                next_steps=state_dict.get("next_steps", []),
            )
        return True

    except Exception as e:
        print(f"Error creating state object: {e}")
        return False

def agent_loop(model: str, api_key: str, max_iterations: int = 15, resume_id: int = None):
    print(
        f"{SUCCESS_COLOR}{SUCCESS_ICON} Spinning up agent...{RESET_COLOR}"
    )
    print(f"{INFO_COLOR}Type 'exit' or press Ctrl+C to quit.{RESET_COLOR}\n")

    if resume_id is not None:
        conv = queries.get_conversation(resume_id)
        if not conv:
            print_error("Resume Error", f"Conversation with ID {resume_id} not found. Starting a new session instead.")
            conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
            conv_row_id = queries.start_conversation(model)
            session_total_tokens = 0
            session_state = Session_state()
        else:
            print(f"{INFO_COLOR}Resuming conversation #{resume_id} ({conv['model']})...{RESET_COLOR}")
            queries.resume_conversation(resume_id)
            conversation = load_conversation(resume_id)
            print_conversation_history(conversation)
            conv_row_id = resume_id
            session_state = Session_state()
            session_total_tokens = conv["total_tokens"] or 0
    else:
        conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
        conv_row_id = queries.start_conversation(model)
        session_total_tokens = 0
        session_state = Session_state()

    show_ttft = True
    last_state_refresh_tokens = 0

    try:
        while True:
            try:
                user_input = input(f"\n{YOU_COLOR}You:{RESET_COLOR} ")
            except (KeyboardInterrupt, EOFError):
                print()
                break

            if not user_input.strip():
                continue

            if user_input.lower() in ["exit", "quit"]:
                break

            conversation.append({"role": "user", "content": user_input.strip()})

            queries.add_message(conversation_id=conv_row_id,role="user",content=user_input.strip())

            spinner = Spinner()
            spinner.start()

            current_iteration = 0

            while current_iteration<=max_iterations:
                current_iteration+=1

                response, prompt_tokens, total_tokens = llm_completions(conversation, model, api_key,spinner=spinner,show_ttft=show_ttft)
                
                if total_tokens is not None:
                    session_total_tokens += total_tokens
                    queries.update_conversation_stats(conv_row_id, session_total_tokens)

                show_ttft=False

                if isinstance(response, str):
                    print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {response}")
                    break

                # to understand what is going on here, go and read the liteLLM response json format.
                try:
                    if hasattr(response, "choices") and response.choices:  # type: ignore
                        # Only the first choice is used for this CLI loop.
                        assistant_message = response.choices[0].message  # type: ignore
                        # The response is being generated by the assistant, depending on whether there are tool calls or not.
                        handle_assistant_message(assistant_message, conversation, conv_row_id, session_state)
                        
                        if not assistant_message.tool_calls:
                            if prompt_tokens is not None and prompt_tokens - last_state_refresh_tokens >= STATE_INJECT_GROWTH:
                                refreshed = refresh_session_state(
                                    conversation,
                                    model,
                                    api_key,
                                    session_state,
                                )
                                if refreshed:
                                    conversation.append({
                                        "role": "system",
                                        "content": f"Internal session state summary:\n{session_state.render()}",
                                    })
                                    last_state_refresh_tokens = prompt_tokens
                            break
                        
                        if prompt_tokens is not None and prompt_tokens > CONTEXT_LIMIT:
                            mask_old_observations(conversation, keep_last_n=1)

                        spinner.start()
                        continue                                     

                    else:
                        # Fallback for unexpected response format
                        content = str(response)
                        print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {content}")
                        conversation.append({"role": "assistant", "content": content})
                        break

                except Exception as e:
                    print(
                        f"{ERROR_COLOR}{ERROR_ICON} Error processing response: {e}{RESET_COLOR}"
                    )
                    print(
                        f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} I encountered an error processing the response."
                    )
                    break

    except KeyboardInterrupt:
        print()

    # Always generate summary and mark completed on exit
    try:
        conv_summary = generate_conversation_summary(conversation, model, api_key)
    except (KeyboardInterrupt, Exception) as e:
        print(f"\n{INFO_COLOR}Summary skipped ({type(e).__name__}){RESET_COLOR}")
        conv_summary = "Untitled session"
    
    queries.mark_conversation_completed(conv_row_id, conv_summary)
    print(f"\n{INFO_COLOR}Goodbye! 👋{RESET_COLOR}")


if __name__ == "__main__":
    agent_loop(model=os.getenv("MODEL",""),api_key=os.getenv("API_KEY",""))
