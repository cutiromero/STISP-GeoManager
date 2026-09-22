# GitHub 长期代码跟踪

建立日期：2026-09-22。用户要求为当前代码建立长期存储与版本跟踪仓库。

## 仓库与分支

- 私有仓库：`https://github.com/cutiromero/STISP-GeoManager`。
- `origin`：上述个人仓库，保存日常开发代码与后续版本。
- `mentor`：`https://github.com/spAurora/GeoManager.git`，保留师兄原仓库地址；本次不推送这里。
- `handoff-bundle`：本机原交接 Git bundle；全部原引用另存于 `refs/handoff/*`。
- `main`：新库当前开发基线。后续任务从它新建 `codex/<area>-<short-task>` 分支，检查通过后提交并推送对应分支，再按实际任务合并。

日常代码备份不需要等待服务器发布；正式发布仍要求同一冻结提交经过新疆服务器候选及生产验收，再保存回执并同步对应版本。这两个步骤分别负责开发记录和生产验收，不混为一谈。

## 首次快照来源

源码来源为师兄 `v0.1.11` / `c8a1d57769ec2eb50a8cbdd283046ba941d02e91`，叠加本机交接说明和独立 Conda 环境配置，最近环境提交为 `cadf17d`。

交接仓库当前运维文档及旧提交存在明文历史口令。新库因此从清理过凭据的当前文件树建立独立首次提交，不把旧提交作为祖先上传。应用代码、测试、必要网页素材、依赖锁文件和开发说明保留；旧运维文档的密码改为本机密码文件说明。

原始 bundle、原始交接材料、旧任务分支和标签均未删除或改写。本机 `codex/agent-local-models`、`codex/handoff-baseline`、`codex/env-local-conda`、`codex/github-code-storage` 及 `refs/handoff/*` 仍可追溯旧历史。它们不应整体上传新库。需要原历史补丁时先审查再移植，不直接合并整个旧祖先链。

旧标签不属于新库首次快照的祖先，不执行整批标签推送。未来新版本从新库历史创建新标签，并与服务器实际验收提交对应。

## 后续同步

已有任务分支完成必要检查后：

```powershell
git status --short
git diff --check
git add -- <本次明确修改的文件>
git commit -m "fix: describe the actual change"
git push -u origin HEAD
```

提交说明按实际工作选择 `feat`、`fix`、`docs` 或 `chore`。主分支已有跟踪关系时，使用普通 `git push`。不使用强制推送、`--all`、`--mirror` 或 `--tags`。发现远端新增提交先检查差异，不用强推覆盖。

只上传代码和必要说明、配置示例及应用素材。`config/app.test.toml`、`.runtime/`、日志、node_modules、Conda 环境及仓库外 `GeoManagerData` 不上传；数据库与科研数据需要独立备份，不能把代码仓库当作完整系统备份。

GitHub Actions 在该仓库关闭，避免首次推送 main 时触发继承的 GHCR 镜像发布任务；历史工作流文件保留。尚未建立任何服务器自动部署或定时推送任务。

GitHub 凭据由现有 Git Credential Manager 提供，不写入远程 URL、脚本正文或仓库。仓库保持私有，后续协作者按需授予访问权限。
