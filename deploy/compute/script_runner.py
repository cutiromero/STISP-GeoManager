"""Trusted controller: user code runs only in a separate confined process."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time

# ==================== CONFIGURATION ====================
RUNTIME = "python-data-script-v1"
MAX_ERROR_BYTES = 8192
MAX_EXECUTION_SECONDS = 90
MAX_CODE_CHARACTERS = 16000
POLICY_VERSION = 1
ENV_KEYS = ("PATH", "PROJ_DATA", "PROJ_LIB", "GDAL_DATA", "GDAL_DRIVER_PATH")
# =======================================================


class ScriptFailure(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(diagnostics["message"])


def diagnostic(error, inputs, working):
    if isinstance(error, ScriptFailure):
        result = dict(error.diagnostics)
    else:
        result = {
            "errorType": type(error).__name__,
            "message": str(error)[:600],
            "line": None,
        }
    message = str(result.get("message", "适配脚本未完成"))[:1200]
    for key, path in inputs.items():
        message = message.replace(str(path), "输入:" + key)
    message = message.replace(str(working), "本次工作目录")
    return {
        "errorType": str(result.get("errorType", "ScriptExecutionError"))[:64],
        "message": message[:600].replace("\x00", ""),
        "line": result.get("line") if type(result.get("line")) is int else None,
    }


def run_child(request_path, working):
    environment = {key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)}
    environment.update(
        HOME=str(working),
        TMPDIR=str(working),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PROJ_NETWORK="OFF",
        GDAL_PAM_ENABLED="NO",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        GDAL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        ARROW_NUM_THREADS="1",
        ARROW_DEFAULT_MEMORY_POOL="system",
        MALLOC_CONF="background_thread:false",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("script_sandbox.py")),
            str(request_path),
        ],
        cwd=working,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    deadline, tail = time.monotonic() + MAX_EXECUTION_SECONDS, bytearray()
    try:
        while True:
            if time.monotonic() >= deadline:
                raise ScriptFailure(
                    {
                        "errorType": "ScriptTimeout",
                        "message": "适配脚本超过90秒，请改用分块处理或缩小本次操作",
                        "line": None,
                    }
                )
            readable, _, _ = select.select([process.stderr], [], [], 0.2)
            if readable:
                chunk = os.read(process.stderr.fileno(), 4096)
                if chunk:
                    tail.extend(chunk)
                    del tail[:-MAX_ERROR_BYTES]
                elif process.poll() is not None:
                    break
            elif process.poll() is not None:
                break
        code = process.wait(timeout=2)
        if code:
            parsed = None
            for line in reversed(
                bytes(tail).decode("utf-8", errors="replace").splitlines()
            ):
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and set(item) == {
                    "errorType",
                    "message",
                    "line",
                }:
                    parsed = item
                    break
            raise ScriptFailure(
                parsed
                or {
                    "errorType": "ScriptProcessError",
                    "message": f"独立脚本进程异常终止（退出码{code}），未采用结果",
                    "line": None,
                }
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stderr.close()


def execute(value, input_dir, output_dir):
    manifest = value["manifest"]
    if manifest["runtime"] != RUNTIME:
        raise ValueError("受限脚本运行器不接受其他运行环境")
    bridge = manifest["inputScriptBridge"]
    if bridge["policyVersion"] != POLICY_VERSION:
        raise ValueError("受限脚本隔离协议版本不可用")
    parameters = value["parameters"]
    code = parameters[bridge["codeParameter"]]
    target_type = parameters[bridge["targetParameter"]]
    contract = json.loads(parameters[bridge["contractParameter"]])
    if (
        not isinstance(code, str)
        or not 1 <= len(code) <= MAX_CODE_CHARACTERS
        or not isinstance(contract, dict)
    ):
        raise ValueError("脚本或目标规范无效")
    output_key = bridge["outputPorts"][target_type]
    spec = next(item for item in manifest["outputs"] if item["key"] == output_key)
    filename = spec["file"]
    if Path(filename).name != filename or Path(filename).is_absolute():
        raise ValueError("脚本结果文件名不合法")
    inputs = {}
    allowed = {name for names in bridge["inputPorts"].values() for name in names}
    if not value["inputs"] or set(value["inputs"]) - allowed:
        raise ValueError("脚本来源超出实际声明范围")
    for key, item in value["inputs"].items():
        portable = item["path"]
        if not portable.startswith("/inputs/"):
            raise ValueError("输入必须为本任务的独立快照")
        path = input_dir / portable.removeprefix("/inputs/")
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(input_dir.resolve())
        ):
            raise ValueError("脚本输入路径越界或已不可用")
        inputs[key] = path.resolve()
    working = output_dir / ".script-work"
    if working.exists() or working.is_symlink():
        raise ValueError("本次脚本工作目录已存在，不能覆盖其他尝试")
    working.mkdir(mode=0o700)
    request_path = output_dir / ".script-request.json"
    request = {
        "code": code,
        "inputs": {key: str(path) for key, path in inputs.items()},
        "workingDirectory": str(working),
        "filename": filename,
        "contract": contract,
    }
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    request_path.chmod(0o600)
    try:
        run_child(request_path, working)
        result = working / filename
        if (
            result.is_symlink()
            or not result.is_file()
            or not result.stat().st_size
            or result.resolve().parent != working.resolve()
        ):
            raise ScriptFailure(
                {
                    "errorType": "MissingScriptOutput",
                    "message": "脚本没有生成声明的真实结果：" + filename,
                    "line": None,
                }
            )
        destination = output_dir / filename
        result.replace(destination)
        if os.geteuid() == 0:
            os.chown(destination, os.geteuid(), os.getegid())
        report = {
            "version": 1,
            "status": "passed",
            "summary": "Agent已完成本次资料衔接，原始资料保持只读。",
            "metrics": {
                "inputCount": len(inputs),
                "outputCount": 1,
                "codeSha256": hashlib.sha256(code.encode()).hexdigest(),
                "isolationPolicyVersion": POLICY_VERSION,
            },
            "knowledgeFacts": {
                "operation": "data_preparation",
                "targetType": target_type,
                "targetSemantics": contract.get("semanticType", ""),
                "originalsReadOnly": True,
            },
        }
        (output_dir / manifest["qualityReport"]["file"]).write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )
    except BaseException as error:
        raise ScriptFailure(diagnostic(error, inputs, working)) from error
    finally:
        request_path.unlink(missing_ok=True)
        shutil.rmtree(working, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--algorithm-dir")  # Never imported or executed.
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    input_dir, output_dir = Path(args.input_dir), Path(args.output_dir)
    status = {"status": "failed"}
    value = {}
    try:
        context_path = input_dir / "context.json"
        if context_path.stat().st_size > 2 * 1024**2:
            raise ValueError("脚本上下文超过上限")
        value = json.loads(context_path.read_text())
        execute(value, input_dir, output_dir)
        status = {"status": "succeeded"}
    except BaseException as error:
        details = diagnostic(error, {}, output_dir)
        status.update(
            error_type=details["errorType"],
            error_detail="输入或参数校验失败",
            scriptDiagnostics=details,
        )
        if details["errorType"] == "ScriptTimeout":
            status["error_category"] = "timeout"
        elif value.get("manifest", {}).get("schemaVersion") == 2:
            status["operatorError"] = {
                "code": "SCRIPT_FAILED",
                "message": details["message"],
                "inputs": [],
                "parameters": [],
                "remedy": "human_review",
                "details": {"scriptDiagnostics": details},
            }
    temporary = output_dir / "__platform_status.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False))
    temporary.replace(output_dir / "__platform_status.json")


if __name__ == "__main__":
    main()
