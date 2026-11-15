"""Preserve Designer arguments while composing its single startup script."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Sequence


def launch(host: str, startup: str, arguments: Sequence[str]) -> int:
    forwarded = []
    user_script = None
    iterator = iter(arguments)
    for argument in iterator:
        if argument == "--":
            forwarded.extend([argument, *iterator])
            break
        if argument == "--startup-script" or argument.startswith("--startup-script="):
            if user_script is not None:
                raise ValueError("Specify only one Designer startup script")
            candidate = argument.partition("=")[2] if "=" in argument else next(iterator, "")
            if not candidate or candidate.startswith("--"):
                raise ValueError("Designer --startup-script requires a file path")
            user_script = str(Path(candidate).resolve(strict=True))
            if not Path(user_script).is_file():
                raise ValueError("Designer startup script must be a file")
            if Path(user_script) == Path(startup).resolve():
                raise ValueError("Caller startup script cannot be the adapter startup script")
        else:
            forwarded.append(argument)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT", None)
    if user_script is not None:
        environment["DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT"] = user_script
    completed = subprocess.run([host, "--startup-script", startup, *forwarded], env=environment, check=False)
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--startup", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    arguments = options.arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    return launch(options.host, options.startup, arguments)


if __name__ == "__main__":
    raise SystemExit(main())
