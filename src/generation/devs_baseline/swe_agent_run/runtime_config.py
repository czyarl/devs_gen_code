"""Runtime settings shared by the SWE-Agent wrappers."""

import os


def docker_args() -> list[str]:
    args = ["--add-host=host.docker.internal:host-gateway"]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        value = os.getenv(f"DEVS_SWE_CONTAINER_{name}")
        if value:
            args.extend(["-e", f"{name}={value}"])
    return args


def docker_image() -> str:
    return os.getenv("DEVS_SWE_DOCKER_IMAGE") or "python-xdevs-simpy"
