from basic_eval import Result,Verdict,Task,file_grader,content_grader
import tempfile
from typing import Callable
from pathlib import Path
import os
from agent.coding_agent import agent_loop

api_key:str | None = os.getenv("API_KEY")
model: str | None = os.getenv("MODEL")

def runner(task:Task,n_trials:int):
    cwd = Path.cwd()
    verdicts = {grader:[]for grader in task.graders}
    for i in range(n_trials):    
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(Path(tmpdir).absolute())   
            try:
                llm_output = None
                if api_key and model:
                    llm_output = agent_loop(model=model,api_key=api_key,evalmode=True,agent_input=task.agent_input)
            finally:
                os.chdir(cwd)
            # Let the LLM produce an output from task.agent_input
            # print(llm_output)
            result = Result(llm_output,Path(tmpdir).absolute())
            for grader in task.graders:
                verdicts[grader].append(grader(result))
    return verdicts

task = Task("Creating and editing a file","Create notes.txt containing a greeting, hello world",[file_grader,content_grader])

print(runner(task,3))

