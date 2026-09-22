---
alwaysApply: true
scene: git_message
---

# AI 生成 Git 提交信息规则

## 格式
<类型>(<范围>): <主题>

<说明>

<关联>

## 类型（选其一）
feat 新功能 / fix 修复 / docs 文档 / perf 优化 / refactor 重构 / test 测试 / build 构建 / revert 回滚
含 BREAKING CHANGE 则加感叹号，如 feat!

## 范围
从改动文件路径取一个词，多个不相关模块用 global

## 主题
≤72字符，现在时祈使句，不加句号

## 说明（必填）
1-2段自然语言，不用列表。写：背景→做法→影响

## 关联（可选）
BREAKING CHANGE: 具体影响
Refs: #123

## 禁止
表情 / 列表 / “我们” / 编造功能

## 示例
feat(payment): 增加每日限额检查

之前不检查每日限额。现在调用网关前校验，超出抛错。客户端需处理新错误码。