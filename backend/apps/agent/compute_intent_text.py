"""Extract explicit user choices; algorithm defaults never confirm a band."""

import re


def _integer(text):
    if text.isdecimal():
        return int(text)
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if "十" in text:
        left, right = text.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(text)


def aliases(spec):
    key, label = spec["key"], spec["label"]
    names = {key, label, re.sub(r"[（(].*", "", label).strip()}
    if spec["type"] == "band":
        names.add(re.sub(r"(?:波段|编号|号)$", "", label).strip())
        for semantic, values in {
            "nir": {"近红外", "近红外波段", "红外", "红外波段"},
            "red": {"红光", "红光波段", "红"},
            "green": {"绿光", "绿光波段", "绿"},
            "blue": {"蓝光", "蓝光波段", "蓝"},
        }.items():
            if key.lower() == semantic:
                names |= values
    return sorted((name for name in names if name), key=len, reverse=True)


def explicit_parameters(prompt, manifest):
    """Return only unambiguous choices written in the current user message."""
    values, conflicts = {}, []
    number = r"[0-9]+|[一二三四五六七八九十两]+"
    for spec in manifest.get("parameters", []):
        names = "(?:" + "|".join(re.escape(name) for name in aliases(spec)) + ")"
        kind = spec["type"]
        found = []
        if kind == "band":
            patterns = [
                rf"(?<![A-Za-z0-9近外]){names}\s*(?:波段)?\s*(?:对应|改为|改成|调整为|仍然是|仍为|仍|为|是|=|：|:)?\s*(?:第\s*)?({number})\s*(?:个)?\s*(?:波段)?",
                rf"第?\s*({number})\s*(?:个)?\s*波段\s*(?:是|为|对应|=|：|:)\s*{names}(?![\w外光])",
            ]
            for pattern in patterns:
                found += [
                    _integer(match.group(1))
                    for match in re.finditer(pattern, prompt, re.IGNORECASE)
                ]
        elif kind in {"integer", "number"}:
            for match in re.finditer(
                rf"(?<!\w){names}\s*(?:=|：|:|为|是)\s*(-?\d+(?:\.\d+)?)",
                prompt,
                re.IGNORECASE,
            ):
                value = (
                    float(match.group(1))
                    if "." in match.group(1)
                    else int(match.group(1))
                )
                found.append(value)
        elif kind == "boolean":
            for match in re.finditer(
                rf"(?<!\w){names}\s*(?:=|：|:|为|是)\s*(true|false|是|否)",
                prompt,
                re.IGNORECASE,
            ):
                found.append(match.group(1).lower() in {"true", "是"})
        else:
            for match in re.finditer(
                rf"(?<!\w){names}\s*(?:=|：|:|为|是)\s*[\"']?([^\s，,；;\"']+)",
                prompt,
                re.IGNORECASE,
            ):
                found.append(match.group(1))
        distinct = list(dict.fromkeys(value for value in found if value is not None))
        if len(distinct) == 1:
            values[spec["key"]] = distinct[0]
        elif len(distinct) > 1:
            conflicts.append(spec["key"])
    return values, conflicts


def algorithm_match(prompt, algorithm):
    """Match the registered name or distinctive identifier terms only."""
    name, identifier = algorithm.name, algorithm.identifier
    if name and name.casefold() in prompt.casefold():
        return True
    if identifier and re.search(
        r"(?<![\w-])" + re.escape(identifier) + r"(?![\w-])", prompt, re.IGNORECASE
    ):
        return True
    for token in re.split(r"[-_\s]+", identifier):
        if token.lower() in {
            "raster",
            "vector",
            "table",
            "compute",
            "image",
            "data",
            "summary",
            "group",
            "linear",
        }:
            continue
        if len(token) >= 3 and re.search(
            r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
            prompt,
            re.IGNORECASE,
        ):
            return True
    return False


def computation_requested(prompt):
    if re.search(
        r"(?:不要|先不|不需要).{0,6}(?:计算|处理|运行|执行)|原理|介绍|解释|怎么|如何|为什么|公式|区别",
        prompt,
    ):
        return False
    return bool(
        re.search(
            r"计算|处理|运行|执行|使用|利用|(?:^|[，,。\s])用|生成|\b(?:calculate|compute|run)\b",
            prompt,
            re.IGNORECASE,
        )
    )


def followup_question(prompt):
    if re.search(
        r"(?:跑完|算完|计算完(?:成)?|完成)(?:了)?(?:没(?:有)?|吗|么|[？?])"
        r"|结果在哪|结果在哪里|(?:是否|有没有)(?:已经)?入库"
        r"|入库(?:了)?(?:没(?:有)?|吗|么|[？?])|(?:^|\s)入库(?:$|\s)",
        prompt,
    ):
        return True
    if re.fullmatch(
        r"\s*(?:(?:目前|当前|现在|最新|这项|这个|计算|任务|入库|的)\s*)*(?:进度|状态)"
        r"(?:如何|怎样|怎么样|是什么|是啥|呢|到哪了?|到了哪了?)?[。?？！!\s]*",
        prompt,
    ):
        return True
    # A long sentence about vegetation/data state is not a compute status query.
    # Require task context in the same clause, rather than borrowing a negated
    # "do not run algorithms" instruction elsewhere in the user's request.
    return any(
        re.search(r"计算|任务|入库", clause)
        and re.search(
            r"(?:查询|查看|看看|检查|汇报|告诉我).{0,12}(?:进度|状态)"
            r"|(?:进度|状态)(?:如何|怎样|怎么样|是什么|是啥|呢|到哪|到了哪|[？?])"
            r"|(?:什么|啥).{0,3}(?:进度|状态)",
            clause,
        )
        for clause in re.split(r"[，,。；;\n]", prompt)
    )


def user_cancelled_pending_compute(run):
    """Only actual latest user text/selected choices can end an unsubmitted plan."""
    content = run.prompt
    for question in reversed(run.interaction_history):
        if question.get("status") != "answered":
            continue
        answer = question["answer"]
        parts = [answer.get("text", "")]
        for item in question["questions"]:
            value = answer.get("answers", {}).get(item["key"])
            values = value if isinstance(value, list) else [value]
            parts.extend(str(value) for value in values if value is not None)
            parts.extend(
                option["label"]
                for option in item.get("options", [])
                if option["value"] in values
            )
        content = "\n".join(parts)
        break
    if re.search(
        r"(?:不|不要|不用|不需要|无需|别|勿)\s*(?:取消|停止|终止|跳过)", content
    ):
        return False
    return bool(
        re.search(
            r"(?:取消|停止|终止|跳过)(?:本次|本轮|后续|当前|这个|全部|继续)?(?:的)?(?:计算|运算)"
            r"|(?:不再|无需|不要|先不|不需要|不重新)(?:再|重新|继续|进行|执行|启动)?(?:计算|运算)",
            content,
        )
    )


def import_requested(prompt):
    return bool(
        re.fullmatch(
            r"\s*(?:请|帮我|把结果|将结果|现在|立即)*\s*(?:入库|保存到(?:数据)?库|结果入库)[。！!\s]*",
            prompt,
        )
    )
