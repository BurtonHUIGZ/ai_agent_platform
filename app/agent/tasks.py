from crewai import Task
import yaml

def load_prompts():
    with open("./config/prompts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["prompts"]


def load_task_configs():
    with open("./config/tasks.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


class TaskFactory:
    def __init__(self, agents):
        self.agents = agents
        self.prompts = load_prompts()
        self.configs = load_task_configs()

    def create(self, task_name: str, **format_kwargs) -> Task:
        cfg = self.configs[task_name]
        agent = self.agents[cfg["agent"]]
        prompt = self.prompts[cfg["prompt_key"]].format(**format_kwargs)
        return Task(
            description=prompt,
            expected_output=cfg["expected_output"],
            agent=agent
        )


TASK_CONFIGS = load_task_configs()
TASK_FACTORY = None


def init_task_factory(agents):
    global TASK_FACTORY
    TASK_FACTORY = TaskFactory(agents)
