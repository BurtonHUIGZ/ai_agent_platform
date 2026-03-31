from crewai import Task
import yaml

def load_tasks(agents):
    with open("./config/tasks.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    tasks = {}
    for name, cfg in config["tasks"].items():
        agent = getattr(agents, cfg["agent"])
        tasks[name] = Task(
            description=cfg["description"],
            expected_output=cfg["expected_output"],
            agent=agent
        )
    return tasks