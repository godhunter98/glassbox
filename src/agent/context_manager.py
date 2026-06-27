from typing import Any,List,Dict
import json

class Session_state():
    """Manages the state of an active agent session.

    This class tracks the goals, files touched, tool execution blockers, decisions,
    and next steps. It maintains deterministic data (recorded automatically by the
    harness, e.g., files touched and blockers) and non-deterministic data
    (refreshed periodically by the model, e.g., current goal, decisions, and next steps).
    This state can be rendered into a compact format to inject into the LLM's system
    prompt.
    """
    def __init__(self,goal:str = ""):
        """Initializes a new Session_state instance.

        Args:
            goal (str, optional): The initial high-level goal of the agent session.
                Defaults to an empty string.
        """
        self.goal = goal
        self.files_touched: Dict[str,int] = {}
        self.blockers: Dict[str,dict] = {}
        self.decisions: list[str] = []
        self.next_steps: list[str] = []

    # cheap, every-turn, harness-driven (the deterministic fields)
    def record_file(self, path: str):
        """Records that a file has been touched (read or modified).

        Increments the touch counter for the specified file path to track agent activity.

        Args:
            path (str): The absolute or relative file path being accessed or modified.
        """
        self.files_touched[path] = self.files_touched.get(path, 0) + 1


    def record_blocker(self, tool: str, args: dict,error:str):
        """Records a tool execution blocker when a tool call encounters an error.

        Tracks repeated execution failures for identical tool calls (same tool name and
        arguments) to help the agent recognize when it is stuck or looping.

        Args:
            tool (str): The name of the tool that failed.
            args (dict): The arguments passed to the tool during the failed execution.
            error (str): The error message or exception encountered during execution.
        """
        key = f"{tool}:{json.dumps(args,sort_keys=True)}"
        entry = self.blockers.get(key)
        if entry is None:
            self.blockers[key] = {"count":1,"last_error":error}
        else:
            entry["count"]+=1
            entry["last_error"] = error
        
        
    # periodic, model-driven (the non-deterministic fields)
    def refresh_reasoning(self, goal, decisions, next_steps):
        """Refreshes the model-driven reasoning fields in the session state.

        Updates the current goal and next steps, and appends any newly made decisions to the
        session's list of decisions (avoiding duplicates).

        Args:
            goal (str): The updated high-level goal of the session.
            decisions (list of str): A list of recent decisions made by the agent.
            next_steps (list of str): A list of scheduled next steps for the agent.
        """
        self.goal = goal
        self.next_steps = next_steps
        for d in decisions:
            if d not in self.decisions:
                self.decisions.append(d)
    
    # the inject step — render to a compact block for the model
    def render(self) -> str:
        """Renders the current session state into a formatted summary string.

        Builds a compact text block summarizing the goal, files touched, active blockers
        (tools with 2 or more failed attempts), recent decisions (limited to the 7 most
        recent), and next steps. This rendered block is suitable for injection into the
        agent's context.

        Returns:
            str: A formatted multiline string representing the current session state.
        """
        files = ", ".join(f"{path} ({n}x)" for path, n in self.files_touched.items())
        active_blockers = [
            f"{key} — {v['count']} attempts, last: {v['last_error']}"
            for key, v in self.blockers.items() if v["count"] >= 2       
        ]
        next_steps = ', '.join(self.next_steps)
        recent_decisions = "Here's a list of 7 recent decisions: " + ', '.join(
            f"({num}, {decision})" for num, decision in enumerate(self.decisions[-7:],1)
        )

        lines = [
        f"Goal: {self.goal}",
        f"Files Touched: {files if files else 'None'}",
        f"Blockers: {'; '.join(active_blockers) if active_blockers else 'None'}",
        f"Decisions: {recent_decisions}",
        f"Next Steps: {next_steps if next_steps else 'None'}"
        ]
        
        return "\n".join(lines)


def mask_old_observations(conversation:list,keep_last_n:int=20):
    """Mask the content of older tool-response messages to reduce context size.

    Replaces the ``content`` of tool-role messages that fall outside the most
    recent *last_n_turns* tool responses with a short placeholder string,
    preserving the message structure so the conversation history stays valid
    for the LLM. Messages shorter than 300 characters are left untouched,
    and already-masked messages are skipped to avoid redundant work.

    Note:
        This function mutates *conversation* in place; it does not return a
        new list.

    Args:
        conversation (list): The full conversation history — a list of
            message dicts, each containing at least ``role`` and ``content``
            keys.  Only entries with ``role == "tool"`` are candidates for
            masking.
        last_n_turns (int, optional): The number of most-recent tool
            messages to keep unmasked.  Set to ``0`` or a negative value to
            mask *all* tool messages.  Defaults to ``20``.
    """
    tool_idx = [idx for idx,turn_message in enumerate(conversation) if turn_message["role"] == "tool"]
    if  keep_last_n<=0:
        required_slice = tool_idx
    else:
        required_slice = tool_idx[:-keep_last_n]
    for i in required_slice:
        tool_message = conversation[i]
        
        if tool_message.get("masked"):
            continue
        
        tool_message_length = len(tool_message["content"])
        tool_message_name= tool_message["name"]
        if tool_message_length > 300:
            tool_message["content"] = f"[observation masked | tool={tool_message_name} | {tool_message_length} chars hidden]"
            
            # flag to avoid idempotency
            tool_message["masked"] = True


def truncate_tool_output(content_str: str, tool_name: str) -> str:
    """Truncates the output of a tool based on its name and size limits.

    Applies different length thresholds and truncation strategies depending on the
    type of tool. For example:
    - ``read_file``: Large limit (35k chars) to avoid losing code, truncates tail.
    - ``run_bash_command`` and ``run_existing_bash_script``: Moderate limit (10k chars),
      truncates head to preserve trailing output (which typically contains error/stack trace details).
    - ``edit_file``: Small limit (2k chars), truncates tail.
    - Other tools: Default limit (5k chars), truncates tail.

    Args:
        content_str (str): The raw string output of the tool execution.
        tool_name (str): The name of the tool that was executed.

    Returns:
        str: The truncated tool output string with a placeholder indicating truncation details.
    """
    # 1. For reading files, allow a larger limit to prevent missing code
    if tool_name == "read_file":
        limit = 35_000
        if len(content_str) > limit:
            return content_str[:limit] + f"\n... [File content truncated: {len(content_str) - limit} characters omitted for context space] ..."
            
    # 2. For bash executions, keep a moderate limit but keep the END of the output
    # (since stack traces and summaries are usually at the bottom)
    elif tool_name in ["run_bash_command", "run_existing_bash_script"]:
        limit = 10_000
        if len(content_str) > limit:
            return f"... [First {len(content_str) - limit} characters truncated for context space] ...\n" + content_str[-limit:]

    # 3. For edits, the response is just a confirmation — keep it small
    elif tool_name == "edit_file":
        limit = 2_000
        if len(content_str) > limit:
            return content_str[:limit] + f"\n... [Truncated {len(content_str) - limit} characters] ..."

    # 4. For other tools (like listing files)
    else:
        limit = 5_000
        if len(content_str) > limit:
            return content_str[:limit] + f"\n... [Truncated {len(content_str) - limit} characters] ..."
            
    return content_str

def prune_conversation(conversation:List[Dict[str,Any]],preserve_last_n:int=3):
    """Prunes older messages from the conversation history to manage context window constraints.

    .. note::
       This function is currently a placeholder and needs to be implemented.

    Args:
        conversation (List[Dict[str, Any]]): The conversation history to be pruned.
    """
       
    groups = []
    current_group = []
    for index,exchange in enumerate(conversation):
        if exchange["role"] == "system" or exchange["role"] == "user":
            if len(current_group) > 0:
                groups.append(current_group)     
            current_group = [index]
        else:
            current_group.append(index)
    if current_group:
        groups.append(current_group)

    if len(groups) > preserve_last_n +2:        
        kept_conversation = []
        kept_groups = groups[:2] + groups[-preserve_last_n:]
        # flattening these lists of lists into kept_conversation via double looping
        for group in kept_groups:
            for indice in group:
                kept_conversation.append(conversation[indice])
        conversation[:] = kept_conversation
        return conversation        

if __name__ == "__main__":
    print("--- Running context_manager.py Tests ---")
    
    # 1. Test Session_state
    print("\n1. Testing Session_state:")
    state = Session_state(goal="Refactor code structure")
    
    # Record files touched
    state.record_file("src/agent/coding_agent.py")
    state.record_file("src/agent/context_manager.py")
    state.record_file("src/agent/coding_agent.py")  # Record again to verify increment
    
    # Record blockers
    state.record_blocker("read_file", {"path": "non_existent.py"}, "FileNotFoundError: No such file")
    state.record_blocker("run_bash_command", {"command": "pytest"}, "Exit code 1: 3 tests failed")
    state.record_blocker("read_file", {"path": "non_existent.py"}, "FileNotFoundError: Still not found") # Same tool & args
    
    print("Goal:", state.goal)
    print("Files touched (expected 'coding_agent.py': 2, 'context_manager.py': 1):")
    print(" ", state.files_touched)
    print("Blockers (expected 'read_file' count: 2, 'run_bash_command' count: 1):")
    for key, data in state.blockers.items():
        print(f"  {key} -> {data}")

    # 2. Test mask_old_observations
    print("\n2. Testing mask_old_observations:")
    dummy_convo = [
        {"role": "user", "content": "Let's read a file"},
        {"role": "assistant", "content": "Sure.", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "line 1\n" * 100}, # Length > 300
        {"role": "user", "content": "Now run a command"},
        {"role": "assistant", "content": "Executing...", "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "run_bash_command", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_2", "name": "run_bash_command", "content": "output\n" * 100}, # Length > 300
        {"role": "user", "content": "Done"}
    ]
    
    print("Original conversation length:", len(dummy_convo))
    # Keep only the last 1 tool message unmasked
    mask_old_observations(dummy_convo, keep_last_n=1)
    
    print("After masking (keep_last_n=1):")
    for msg in dummy_convo:
        if msg["role"] == "tool":
            print(f"  Tool ({msg.get('name')}): {msg['content'][:80]}... (masked={msg.get('masked', False)})")

    # 3. Test truncate_tool_output
    print("\n3. Testing truncate_tool_output:")
    long_read = "abc\n" * 10000  # 40000 chars
    long_bash = "line\n" * 3000   # 15000 chars
    
    truncated_read = truncate_tool_output(long_read, "read_file")
    truncated_bash = truncate_tool_output(long_bash, "run_bash_command")
    
    print(f"  read_file output size: {len(long_read)} -> {len(truncated_read)}")
    print(f"  run_bash_command output size: {len(long_bash)} -> {len(truncated_bash)}")
    print("  First line of truncated bash:", truncated_bash.splitlines()[0])
    print("  Last line of truncated bash:", truncated_bash.splitlines()[-1])

    # 4. Test prune_conversation
    print("\n4. Testing prune_conversation:")
    prune_convo = [
        {"role": "system", "content": "You are a helpful assistant."},                          # group 0
        {"role": "user", "content": "Turn 1: Read my config"},                                  # group 1 start
        {"role": "assistant", "content": "Turn 1: Sure, reading config.", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "port=8080"},    # group 1 end
        {"role": "user", "content": "Turn 2: Fix the port"},                                    # group 2 start
        {"role": "assistant", "content": "Turn 2: Fixed the port."},                             # group 2 end
        {"role": "user", "content": "Turn 3: Run tests"},                                       # group 3 start
        {"role": "assistant", "content": "Turn 3: Running tests.", "tool_calls": [{"id": "c2"}]},
        {"role": "tool", "tool_call_id": "c2", "name": "run_bash_command", "content": "PASS"},   # group 3 end
        {"role": "system", "content": "Session state: Goal is to fix config"},                   # group 4 (injected state)
        {"role": "user", "content": "Turn 4: Deploy it"},                                       # group 5 start
        {"role": "assistant", "content": "Turn 4: Deploying now."},                              # group 5 end
        {"role": "user", "content": "Turn 5: Check status"},                                    # group 6 start
        {"role": "assistant", "content": "Turn 5: All good!", "tool_calls": [{"id": "c3"}]},
        {"role": "tool", "tool_call_id": "c3", "name": "run_bash_command", "content": "200 OK"}, # group 6 end
        {"role": "user", "content": "Turn 6: Thanks!"},                                         # group 7 start
        {"role": "assistant", "content": "Turn 6: You're welcome!"},                             # group 7 end
    ]

    print(f"  Before pruning: {len(prune_convo)} messages")
    print(f"  Messages: {[m['content'][:30] for m in prune_convo]}")
    
    prune_conversation(prune_convo, preserve_last_n=2)
    
    print(f"\n  After pruning (preserve_last_n=2): {len(prune_convo)} messages")
    print(f"  Surviving messages:")
    for msg in prune_convo:
        print(f"    [{msg['role']}] {msg['content'][:50]}")