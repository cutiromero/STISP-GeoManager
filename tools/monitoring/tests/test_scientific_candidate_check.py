"""The release hook accepts only after both domain checks complete successfully."""

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scientific_candidate_check.py"
SPEC = importlib.util.spec_from_file_location("scientific_candidate_check", SOURCE)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@pytest.mark.parametrize("failed", [False, True])
def test_combined_candidate_acceptance_requires_every_check(
    tmp_path, monkeypatch, capsys, failed
):
    context = tmp_path / "context.json"
    code = tmp_path / "candidate/code"
    context.write_text(json.dumps({"code": str(code)}))
    monkeypatch.setattr("sys.argv", [str(SOURCE), "--context", str(context)])
    executed = []

    def run(path, *, run_name):
        assert run_name == "__main__"
        executed.append(Path(path).relative_to(code).as_posix())
        print(json.dumps({"ready": True}))
        if failed and len(executed) == 2:
            raise RuntimeError("observation check failed")

    monkeypatch.setattr(hook.runpy, "run_path", run)
    if failed:
        with pytest.raises(RuntimeError, match="observation check failed"):
            hook.main()
        assert '"accepted"' not in capsys.readouterr().out
    else:
        hook.main()
        receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert receipt == {
            "accepted": True,
            "checks": {name: True for name in hook.CHECKS},
        }
    assert executed == hook.CHECKS
