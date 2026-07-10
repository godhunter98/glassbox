import subprocess
from typing import Dict, Any
import types
# Builtin types that don't have constructors in the built-in namespace (e.g. functions, generators, methods)
from pathlib import Path
import json
import inspect
from typing import get_type_hints

from agent.ui import (
    TOOL_COLOR,
    INFO_COLOR,
    RESET_COLOR,
    TOOL_ICON,
    SUCCESS_COLOR,
    SUCCESS_ICON,
    ERROR_COLOR,
    ERROR_ICON,
    FILE_ICON,
    DIR_ICON,
)

SUBPROCESS_TIMEOUT = 30

tool_definitions = list()
tool_schema = tool_definitions
tool_registry = dict()

# Decorator to register_tool names, their func and creating a tool_schema for each on the fly.
def register_tool(func:types.FunctionType):
    """Register a function as a tool"""
    tool_registry[func.__name__] = func

    single_schema = dict()

    single_schema["type"] = "function"
    single_schema["name"] = func.__name__
    single_schema["description"] = func.__doc__ or "No description provided"

    # to undertand what's going here, you need to look at what a typical schema looks like!
    single_schema["parameters"] = dict()
    

    hints = get_type_hints(func)
    sig = inspect.signature(func)

    properties = {}
    required = []
    TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
    
    for param_name, param in sig.parameters.items():
        json_type = TYPE_MAP.get(hints.get(param_name, str), "string")
        properties[param_name] = {
            "type": json_type,
            "description": f"Parameter {param_name}"
        }
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    single_schema["parameters"] = {
        "type": "object",
        "properties": properties,
        "required": required
    }

    tool_definitions.append(single_schema)

    return func

UNSAFE_PATTERNS = [
    # Destructive file operations
    "rm -rf", "rm -f", "rmdir", "rm",
    # Disk/partition operations
    "mkfs", "fdisk", "dd if=",
    # Privilege escalation
    "sudo", "su ",
    # Network transfer
    "curl", "wget",
    # Redirect overwrite to root paths
    "> /",
    # Process/system manipulation
    "kill -9", "shutdown", "reboot",
    # Environment tampering
    "export path=", "unset path",
]

def is_unsafe(command: str) -> bool:
    normalized = command.strip().lower()
    return any(pattern in normalized for pattern in UNSAFE_PATTERNS)

@register_tool
def run_bash_command(command: str) -> Dict[str, Any]|str:
    # safety check
    if is_unsafe(command):
        print(f"{ERROR_COLOR}{ERROR_ICON} Potentially unsafe command: {command}{RESET_COLOR}")
        confirm = input("Run anyway? (y/N): ").strip().lower()
        if confirm != "y":
            return {
                "command": command,
                "error": "Cancelled by user",
                "success": False,
            }
    print(
        f"{TOOL_COLOR}{TOOL_ICON} Running bash command: {INFO_COLOR}{command}{RESET_COLOR}"
    )
    try:
        # Run the command and capture output
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=True,timeout=SUBPROCESS_TIMEOUT
        )
        print(
            f"{SUCCESS_COLOR}{SUCCESS_ICON} Command executed successfully{RESET_COLOR}"
        )
        print(f"{INFO_COLOR}STDOUT:{RESET_COLOR} {result.stdout}")
        if result.stderr:
            print(f"{INFO_COLOR}STDERR:{RESET_COLOR} {result.stderr}")
        return {
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": True,
        }
    except subprocess.CalledProcessError as e:
        print(
            f"{ERROR_COLOR}{ERROR_ICON} Command failed with exit code {e.returncode}{RESET_COLOR}"
        )
        print(f"{INFO_COLOR}STDOUT:{RESET_COLOR} {e.stdout}")
        print(f"{INFO_COLOR}STDERR:{RESET_COLOR} {e.stderr}")
        return {
            "command": command,
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
            "success": False,
            "error": f"Command failed with exit code {e.returncode}",
        }
    except subprocess.TimeoutExpired:
        print(f"{ERROR_COLOR}{ERROR_ICON} The command {command} took too long to run!{RESET_COLOR}")
        return {
            "command": command,
            "success": False,
            "error": f"Command timed out after {SUBPROCESS_TIMEOUT} seconds!",
        }

@register_tool
def run_existing_bash_script(script_path: str) -> Dict[str, Any]:
    full_path = resolve_abs_path(script_path)
    try:
        script_content = full_path.read_text(encoding="utf-8")
        if is_unsafe(script_content):
            print(f"{ERROR_COLOR}{ERROR_ICON} Potentially unsafe script: {script_path}{RESET_COLOR}")
            confirm = input("Run anyway? (y/N): ").strip().lower()
            if confirm != "y":
                return {
                    "script_path": str(full_path),
                    "error": "Cancelled by user",
                    "success": False,
                }
    except Exception:
        pass  # If we can't read it, let subprocess handle the error
    print(
        f"{TOOL_COLOR}{TOOL_ICON} Running bash script: {INFO_COLOR}{script_path}{RESET_COLOR}"
    )
    try:
        # Run the script with bash
        result = subprocess.run(
            ["bash", str(full_path)], capture_output=True, text=True, check=True,timeout=SUBPROCESS_TIMEOUT
        )
        print(
            f"{SUCCESS_COLOR}{SUCCESS_ICON} Script executed successfully{RESET_COLOR}"
        )
        print(f"{INFO_COLOR}STDOUT:{RESET_COLOR} {result.stdout}")
        if result.stderr:
            print(f"{INFO_COLOR}STDERR:{RESET_COLOR} {result.stderr}")
        return {
            "script_path": str(full_path),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": True,
        }
    except subprocess.CalledProcessError as e:
        print(
            f"{ERROR_COLOR}{ERROR_ICON} Script failed with exit code {e.returncode}{RESET_COLOR}"
        )
        print(f"{INFO_COLOR}STDOUT:{RESET_COLOR} {e.stdout}")
        print(f"{INFO_COLOR}STDERR:{RESET_COLOR} {e.stderr}")
        return {
            "script_path": str(full_path),
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
            "success": False,
            "error": f"Script failed with exit code {e.returncode}",
        }
    except subprocess.TimeoutExpired:
        print(f"{ERROR_COLOR}{ERROR_ICON} The script  took too long - {SUBPROCESS_TIMEOUT} seconds to run!{RESET_COLOR}")
        return {
            "script": script_path,
            "success": False,
            "error": f"The script took too long to run and timed out after {SUBPROCESS_TIMEOUT} seconds!",
        }


def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def get_tool_schema(model: str | None = None) -> list[dict]:
    """Return tools in the schema format expected by the current provider."""
    if model and "deepseek" in model.lower():
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tool_definitions
        ]
    return [tool.copy() for tool in tool_definitions]

@register_tool
def read_file(filename: str) -> Dict[str, Any]:
    """ A simple tool to read any kind of files, just provide the filename with its extension"""
    full_path = resolve_abs_path(filename)
    print(f"{TOOL_COLOR}{TOOL_ICON} Reading file: {INFO_COLOR}{filename}{RESET_COLOR}")
    try:
        with open(str(full_path), "r", encoding="utf-8") as f:
            content = f.read()
        return {"file_path": str(full_path), "content": content}
    except Exception as e:
        print(f"{ERROR_COLOR}{ERROR_ICON} Error reading file: {e}{RESET_COLOR}")
        return {"file_path": str(full_path), "content": "", "error": str(e)}

@register_tool
def list_file(path: str) -> Dict[str, Any]:
    full_path = resolve_abs_path(path)
    print(
        f"{TOOL_COLOR}{TOOL_ICON} Listing directory: {INFO_COLOR}{full_path}{RESET_COLOR}"
    )
    all_files = []
    for item in full_path.iterdir():
        icon = FILE_ICON if item.is_file() else DIR_ICON
        if not item.name.startswith(".env"):
            all_files.append(
                {
                    "icon": icon,
                    "filename": item.name,
                    "type": "file" if item.is_file() else "dir",
                }
            )
    return {"path": str(full_path), "files": all_files}


@register_tool
def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    full_path = resolve_abs_path(path)
    try:
        if old_str == "":
            print(
                f"{TOOL_COLOR}{TOOL_ICON} Creating file: {INFO_COLOR}{path}{RESET_COLOR}"
            )
            full_path.write_text(new_str, encoding="utf-8")
            print(
                f"{SUCCESS_COLOR}{SUCCESS_ICON} File created successfully{RESET_COLOR}"
            )
            return {"path": str(full_path), "action": "created_file"}

        original = full_path.read_text(encoding="utf-8")
        if original.find(old_str) == -1:
            print(
                f"{ERROR_COLOR}{ERROR_ICON} Text to replace not found in file{RESET_COLOR}"
            )
            return {"path": str(full_path), "action": "old_str not found"}

        print(f"{TOOL_COLOR}{TOOL_ICON} Editing file: {INFO_COLOR}{path}{RESET_COLOR}")
        edited = original.replace(old_str, new_str, 1)
        full_path.write_text(edited, encoding="utf-8")
        print(f"{SUCCESS_COLOR}{SUCCESS_ICON} File edited successfully{RESET_COLOR}")
        return {"path": str(full_path), "action": "edited"}
    except Exception as e:
        print(f"{ERROR_COLOR}{ERROR_ICON} Error editing file: {e}{RESET_COLOR}")
        return {"path": str(full_path), "action": "error", "error": str(e)}
    
