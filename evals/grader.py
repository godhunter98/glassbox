from basic_eval import Result,Verdict,Task,file_grader,content_grader
import tempfile
from typing import Callable
from pathlib import Path
import os
from agent.coding_agent import agent_loop

api_key = os.getenv("API_KEY")
model: str | None = os.getenv("MODEL")

def runner(task:Task,n_trials:int):
    cwd = Path.cwd()
    verdicts = {grader:[]for grader in task.graders}
    for i in range(n_trials):    
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(Path(tmpdir).absolute())   
            try:
                llm_output = agent_loop(model,api_key)
            finally:
                os.chdir(cwd)
            # Let the LLM produce an output from task.agent_input
            result = Result(llm_output,Path(tmpdir).absolute())
            for grader in task.graders:
                verdicts[grader].append(grader(result))

task = Task("Creating and editing a file","Create notes.txt containing a greeting, hello world",[file_grader,content_grader])

runner(task,3)