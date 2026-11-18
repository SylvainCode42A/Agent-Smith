import json
from pathlib import Path
from agent_swebench.docker import (launch_docker,
                                   start_container,
                                   copy_eval_script,
                                   remove_container)


TASK = (Path(__file__).resolve().parents[2] / "cache" /
        "swe_14711" / "task.json")

with open(TASK) as f:
    task = json.load(f)

image = task["docker_image"]
script = task["eval_script"]


name = "try_smith"
remove_container(name)

try:
    start_container(image, name)
    copy_eval_script(name, script)
    lu = launch_docker(["exec", name, "cat", "/tmp/agent/eval.sh"]).stdout
    assert lu == script, "eval.sh in the Docker != eval_script"
    print("copy OK")
    res = launch_docker(["exec", name, "bash", "/tmp/agent/eval.sh"])
    debut = res.stdout.find("test process starts")
    if debut == -1:
        debut = 0
    print(res.stdout[debut:])
finally:
    remove_container(name)
    remove_container(name)
    remove_container("")

rest = launch_docker(["ps", "-a", "--filter", "name=try_smith", "-q"])
assert rest.stdout.strip() == "", f"last contener: {rest.stdout}"
print("docker OK")
