import pytest
import os
from agent.main import main
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
import litellm
from enum import Enum

load_dotenv()

api_key = os.getenv("API_KEY")
model: str | None = os.getenv("MODEL")

class Verdict(Enum):
    PASS = 1
    FAIL = 2
    UNKNOWN = 3
    

def check_file_creation(filename:str,file_content:str,match:Literal["contains","exact"]="contains"): 
    '''
    After the test run, we're checking for whether the file exists at a specific path and if the contents of the file match what we asked 
    the agent to populate.
    '''
    try:
        current_location = Path.cwd()
        file_path = current_location / filename 

        if file_path.exists():
            with file_path.open("r") as file:
                content = file.read()
                if match == "contains"and  file_content.strip() in content.strip():
                    return Verdict.PASS
                elif match == "exact" and content.strip() == file_content.strip():
                    return Verdict.PASS
                else:
                    Verdict.FAIL
        else: 
            return Verdict.FAIL
    except Exception:
        return Verdict.UNKNOWN

def judge_file_content(task:str,actual_content:str,model:str,api_key:str):
    prompt = f"""You are evaluating whether an agent completed a task correctly.
    Task the agent was given: {task}
    Output the agent produced: {actual_content}
    Does the output satisfy the task? Respond with exactly one word: PASS, FAIL or UNKNOWN.
    """
    conversation = [{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":prompt}]
    try:
        response = litellm.completion(model=model,api_key=api_key,messages=conversation,temperature=0)
        content: str|None = response.choices[0].message.content
        result = content.strip().lower()

        if result == "pass":
            return Verdict.PASS
        elif result == "fail":
            return Verdict.FAIL
        else:
            return Verdict.UNKNOWN
    except Exception:
        return Verdict.UNKNOWN


print(check_file_creation("test.txt","hey there",match="contains"))

print(judge_file_content(
    task="What is 7x + 27, when x is 2, give only the answer and no greetings, nothing?",
    actual_content="42",
    model=model,
    api_key=api_key,
))