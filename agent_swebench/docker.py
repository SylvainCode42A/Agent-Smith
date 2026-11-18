import subprocess


RUN_TIMEOUT = 300   # docker run may pull a ~4 GB image first
EXEC_TIMEOUT = 30   # copying eval.sh
RM_TIMEOUT = 15     # cleanup, possibly during SIGTERM


def check(res, context):
    """Raise a readable RuntimeError if the docker command failed."""

    if res.returncode == 0:
        return
    stderr = res.stderr.strip()
    message = f"{context} : {stderr}"
    if "docker.sock" in stderr or "daemon is running" in stderr:
        message += " (No response from Docker : launch `colima start`)"
    raise RuntimeError(message)


def launch_docker(args, input=None, timeout=None):
    """Run `docker <args>` and return the CompletedProcess."""

    return subprocess.run(
        ["docker"] + args,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout
    )


def start_container(image, name):
    """Start a detached amd64 container that sleeps forever. Return its id."""

    try:
        res = launch_docker(["run", "-d", "--platform", "linux/amd64",
                             "--name", name, image, "sleep", "infinity"],
                            timeout=RUN_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("Docker not found - Is Docker installed?") from None
    except subprocess.TimeoutExpired:
        remove_container(name)
        raise RuntimeError(
            f"Timeout ({RUN_TIMEOUT}s) starting {name} from {image}"
        ) from None

    check(res, f"Failed to start {name} from {image}")
    return res.stdout.strip()


def copy_eval_script(name, script):
    """Write script to /tmp/agent/eval.sh inside the container."""

    try:
        res = launch_docker(["exec", "-i", name, "sh", "-c",
                             "mkdir -p /tmp/agent && cat "
                             "> /tmp/agent/eval.sh"],
                            input=script, timeout=EXEC_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("Docker not found - Is Docker installed?") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Timeout ({EXEC_TIMEOUT}s) copying eval.sh in {name}"
        ) from None

    check(res, f"Failed to copy eval.sh in {name}")


def remove_container(name):
    """Force-remove the container. Never raises; does
    nothing if name is empty."""

    if not name:
        return

    try:
        launch_docker(["rm", "-f", name], timeout=RM_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        pass
