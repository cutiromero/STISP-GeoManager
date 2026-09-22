"""Trusted minimal SDK runner for container and native-process execution."""

import contextlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


class Context:
    def __init__(self, request, input_dir, output_dir):
        self.inputs = request["inputs"]
        self.parameters = request["parameters"]
        self.input_dir = input_dir
        self.output_dir = output_dir

    def input_path(self, key):
        path = Path(self.inputs[key]["path"])
        portable = path.as_posix()
        if portable.startswith("/inputs/"):
            return self.input_dir / portable.removeprefix("/inputs/")
        return path

    def output_path(self, filename):
        path = self.output_dir / filename
        if path.parent != self.output_dir:
            raise ValueError("Output must be a single filename")
        return path


def main():
    # No platform secrets or database connection are present in this environment.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--algorithm-dir",
        default=os.environ.get("GEOMANAGER_ALGORITHM_DIR", "/algorithm"),
    )
    parser.add_argument(
        "--input-dir", default=os.environ.get("GEOMANAGER_INPUT_DIR", "/inputs")
    )
    parser.add_argument(
        "--output-dir", default=os.environ.get("GEOMANAGER_OUTPUT_DIR", "/output")
    )
    options, _ = parser.parse_known_args()
    algorithm_dir = Path(options.algorithm_dir)
    input_dir = Path(options.input_dir)
    output_dir = Path(options.output_dir)
    request = json.loads((input_dir / "context.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(algorithm_dir))
    status = "failed"
    try:
        with (
            open(os.devnull, "w") as null,
            contextlib.redirect_stdout(null),
            contextlib.redirect_stderr(null),
        ):
            spec = importlib.util.spec_from_file_location(
                "operator_main", algorithm_dir / "main.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.run(Context(request, input_dir, output_dir))
        status = "succeeded"
    except BaseException:
        pass
    temporary = output_dir / "__platform_status.tmp"
    temporary.write_text(json.dumps({"status": status}), encoding="utf-8")
    temporary.replace(output_dir / "__platform_status.json")
    # Keep bounded tmpfs alive for the host to retrieve declared files.
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
