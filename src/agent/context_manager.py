
def truncate_tool_output(content_str: str, tool_name: str) -> str:
    # 1. For reading files, allow a larger limit to prevent missing code
    if tool_name == "read_file":
        limit = 16000
        if len(content_str) > limit:
            return content_str[:limit] + f"\n... [File content truncated: {len(content_str) - limit} characters omitted for context space] ..."
            
    # 2. For bash executions, keep a moderate limit but keep the END of the output
    # (since stack traces and summaries are usually at the bottom)
    elif tool_name in ["run_bash_command", "run_existing_bash_script"]:
        limit = 6000
        if len(content_str) > limit:
            return f"... [First {len(content_str) - limit} characters truncated for context space] ...\n" + content_str[-limit:]
            
    # 3. For other tools (like listing files)
    else:
        limit = 3000
        if len(content_str) > limit:
            return content_str[:limit] + f"\n... [Truncated {len(content_str) - limit} characters] ..."
            
    return content_str
