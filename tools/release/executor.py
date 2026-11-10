"""所有 SSH / SCP 操作的唯一入口；默认离线计划。"""

import shlex
import subprocess

AUTH_OPTIONS = (
    "BatchMode=yes",
    "PasswordAuthentication=no",
    "KbdInteractiveAuthentication=no",
    "PreferredAuthentications=publickey",
    "StrictHostKeyChecking=yes",
)


class Executor:
    def __init__(self, config, *, execute=False):
        self.config = config
        self.execute = execute

    def _options(self):
        return [
            part
            for value in (*self.config["ssh"]["options"], *AUTH_OPTIONS)
            for part in ("-o", value)
        ]

    def _run(self, command, *, payload=None, timeout=None):
        if not self.execute:
            print("计划（未连接）：" + shlex.join(command[:4]) + " …")
            return b""
        return subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or self.config["local"]["commandSeconds"],
            check=True,
        ).stdout

    def ssh(self, command, *, payload=None, timeout=None):
        ssh = self.config["ssh"]
        return self._run(
            [
                "ssh",
                "-p",
                str(ssh["port"]),
                *self._options(),
                f"{ssh['user']}@{ssh['host']}",
                shlex.join(command),
            ],
            payload=payload,
            timeout=timeout,
        )

    def upload(self, source, destination):
        ssh = self.config["ssh"]
        return self._run(
            [
                "scp",
                "-P",
                str(ssh["port"]),
                *self._options(),
                str(source),
                f"{ssh['user']}@{ssh['host']}:{shlex.quote(str(destination))}",
            ]
        )

    def origin_head(self, repo, branch):
        output = self._run(
            [
                "git",
                "-C",
                str(repo),
                "ls-remote",
                "--refs",
                "origin",
                "refs/heads/" + branch,
            ]
        )
        return output.decode().split()[0] if output else None
