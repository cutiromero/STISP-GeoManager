"""Run both domain checks through the standard isolated candidate context."""

import argparse
import json
from pathlib import Path
import runpy

# CONFIGURATION
CHECKS = ["tools/spartina/candidate_check.py", "tools/wildfire/candidate_check.py"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    context = json.loads(parser.parse_args().context.read_text())
    code = Path(context["code"]).resolve()
    for name in CHECKS:
        runpy.run_path(str(code / name), run_name="__main__")
    print(json.dumps({"accepted": True, "checks": {name: True for name in CHECKS}}))


if __name__ == "__main__":
    main()
