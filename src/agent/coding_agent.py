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
from agent.context_manager import truncate_tool_output

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
                        "content": truncate_tool_output(tc["tool_output"])
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
            "max_tokens": 2000,
            "temperature": 0.1,
            "tools": get_tool_schema(model),
            "stream":True,
            "thinking": {"type": "disabled"}
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
                text_token_count = 0

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

                # Estimate token count based on English characters: 1 character ≈ 0.3 token
                text_token_count = int(len(accumulated_text) * 0.3)

                full_response = litellm.stream_chunk_builder(chunks)

                if start_time is not None and text_token_count > 0:
                    duration = end_time - start_time
                    tps = text_token_count / duration
                    if show_ttft:
                        print(f"{INFO_COLOR}  [ {ttft:.1f}s - 1st token ]{RESET_COLOR}")
                    if kwargs.get("thinking") == {"type": "disabled"}:
                        print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {text_token_count} tokens in {duration:.2f}s | Thinking_Mode 🧠: ❌ ]{RESET_COLOR}\n")
                    else:
                        print(f"{INFO_COLOR}  [ {tps:.1f} toks/s | {text_token_count} tokens in {duration:.2f}s | Thinking_Mode 🧠 : ✅ ]{RESET_COLOR}\n")

                return full_response, text_token_count
                
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
    tool_call, conversation: List[Dict[str, Any]], index: int , db_msg_id: int
) -> None:
    tool_name = tool_call.function.name
    try:
        # Tool arguments arrive as JSON strings in the model response.
        tool_args = json.loads(tool_call.function.arguments)
        args_display = ", ".join(f"{k}={v}" for k, v in tool_args.items())
        print(f"  {index}. {TOOL_ICON} {tool_name}({args_display})")

        tool = tool_registry.get(tool_name)
        if not tool:
            error_msg = f"Unknown tool: {tool_name}"
            print_error("Tool error", error_msg)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": error_msg}),
                }
            )
            return

        try:
            resp = tool(**tool_args)
            # tool args and tool resp are dicts, but sqlite needs a string, we dump them!
            queries.add_tool_call(db_msg_id,tool_name,json.dumps(tool_args),json.dumps(resp))
            resp_str = truncate_tool_output(json.dumps(resp))
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(resp),
                }
            )
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            print_error("Tool error", error_msg)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": error_msg}),
                }
            )

    except json.JSONDecodeError:
        print("The model sent back a broken JSON string!")

def handle_assistant_message(assistant_message, conversation: List[Dict[str, Any]],conversation_id: int) -> None:
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
        run_tool_call(tool_call, conversation, index, db_msg_id)



def generate_conversation_summary(conversation: List[Dict[str,Any]],model:str,api_key:str) -> str:
    '''Generate a summary from the completed conversation.'''
    print(f"\n{INFO_COLOR}Saving conversation...{RESET_COLOR}")
    
    # We use build_messages to safely format the history
    summary_convo = build_messages(conversation)
    summary_convo.append({
        "role": "user", 
        "content": "Summarize this session in exactly 6 to 8 words. Do not use punctuation. Do not write anything else."
    })
    
    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": summary_convo,
        "max_tokens": 150, 
        "temperature": 0.2,    
        "stream": False,
        "thinking": {"type": "disabled"} 
    }

    try:
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        return content.strip() if content else "Session ended before discussion."
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Summary could not be generated."


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
        else:
            print(f"{INFO_COLOR}Resuming conversation #{resume_id} ({conv['model']})...{RESET_COLOR}")
            queries.resume_conversation(resume_id)
            conversation = load_conversation(resume_id)
            print_conversation_history(conversation)
            conv_row_id = resume_id
            session_total_tokens = conv["total_tokens"] or 0
    else:
        conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
        conv_row_id = queries.start_conversation(model)
        session_total_tokens = 0

    show_ttft = True

    while True:
        try:
            user_input = input(f"\n{YOU_COLOR}You:{RESET_COLOR} ")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{INFO_COLOR}Goodbye! 👋{RESET_COLOR}")
            queries.mark_conversation_completed(conv_row_id)
            break

        if not user_input.strip():
            continue

        if user_input.lower() in ["exit", "quit"]:
            conv_summary = generate_conversation_summary(conversation,model,api_key)
            queries.mark_conversation_completed(conv_row_id,conv_summary)
            print(f"\n{INFO_COLOR}Goodbye! 👋{RESET_COLOR}")
            break

        conversation.append({"role": "user", "content": user_input.strip()})

        queries.add_message(conversation_id=conv_row_id,role="user",content=user_input.strip())

        spinner = Spinner()
        spinner.start()

        current_iteration = 0

        while current_iteration<=max_iterations:
            current_iteration+=1

            response,tokens = llm_completions(conversation, model, api_key,spinner=spinner,show_ttft=show_ttft)
            
            session_total_tokens += tokens
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
                    handle_assistant_message(assistant_message,conversation,conv_row_id)
                    if not assistant_message.tool_calls:
                        break
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


if __name__ == "__main__":
    agent_loop(model=os.getenv("MODEL",""),api_key=os.getenv("API_KEY",""))
