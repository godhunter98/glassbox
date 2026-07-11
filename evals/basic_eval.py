import pytest
import os
from agent.main import main
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
import litellm
from enum import Enum
from dataclasses import dataclass
from typing import Callable
from functools import partial

load_dotenv()

api_key = os.getenv("API_KEY")
model: str | None = os.getenv("MODEL")

class Verdict(Enum):
    PASS = 1
    FAIL = 2
    UNKNOWN = 3

@dataclass
class Result:
    # our result is what the agent outputs and what the current state looks like - state change
    agent_output: str
    workspace: Path

@dataclass
class Task:
    # A single task is the written-down pairing: this input, judged by these graders
    name: str
    agent_input: str
    graders: list[Callable[[Result], Verdict]]


def check_file_creation(result:Result,filename:str,file_content:str,match:Literal["contains","exact"]="contains") -> Verdict: 
    '''
    After the test run, we're checking for whether the file exists at a specific path and if the contents of the file match what we asked 
    the agent to populate.
    '''
    try:
        file_path = result.workspace / filename 

        if file_path.exists():
            with file_path.open("r") as file:
                content = file.read()
                if match == "contains" and file_content.strip() in content.strip():
                    return Verdict.PASS
                elif match == "exact" and content.strip() == file_content.strip():
                    return Verdict.PASS
                else:
                    return Verdict.FAIL
        else: 
            return Verdict.FAIL
    except Exception:
        return Verdict.UNKNOWN

def judge_file_content(result:Result,task:str,model:str,api_key:str) -> Verdict:
    prompt = f"""You are evaluating whether an agent completed a task correctly.
    Task the agent was given: {task}
    Output the agent produced: {result.agent_output}
    Does the output satisfy the task? Respond with exactly one word: PASS, FAIL or UNKNOWN.
    """
    conversation = [{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":prompt}]
    try:
        response = litellm.completion(model=model,api_key=api_key,messages=conversation,temperature=0)
        content: str|None = response.choices[0].message.content
        if content is None:
            return Verdict.UNKNOWN
        output = content.strip().lower()
        if output == "pass":
            return Verdict.PASS
        elif output == "fail":
            return Verdict.FAIL
        else:
            return Verdict.UNKNOWN
    except Exception:
        return Verdict.UNKNOWN

# we're using partial to check and freeze some of the inputs to our function
file_grader = partial(check_file_creation,filename="notes.txt",file_content="Hello world",match="contains")
content_grader = partial(judge_file_content,task="Create notes.txt containing a greeting",model=model,api_key=api_key)