"""Project-owned RGB interpretation using the common main-agent flow runtime."""

from .execution_session import default_skill

CODE = "huanjiang-landcover"


def definition(version_id):
    titles = [
        ("sources", "确认任务资料"),
        ("inputs", "核对输入要求"),
        ("interpret", "地表解译与成果准备"),
        ("statistics", "核验分类统计"),
        ("deliver", "整理展示成果"),
        ("finish", "完成结果交付"),
    ]
    descriptions = [
        "确认选定样区与提取模式。",
        "核对RGB波段、2米分辨率与原始网格。",
        "逐幅执行已登记模型，完成后处理、固定优先级合成和成果准备。",
        "读取实际类别计数、有效区与面积统计。",
        "整理已入库的分类图、统计和大屏成果入口。",
        "交付所选样区成果和对应任务记录。",
    ]
    instructions = [
        "列出本次每份原始资料及用户指定模式，保留全部选定样区。",
        "使用已有元信息核对三波段RGB、2米和米制投影；正式计算预检在解译目标按方案完成一次。",
        "必须对本次image角色中的每一幅影像分别调用冻结版本。使用image端口绑定一个真实资源ID；使用当前节点已配置classes。每幅依次operator_catalog、preflight_operator、run_operator；有成功计算后继续其余影像。全部图和统计实际成功且完成入库后finish_node。",
        "依据上游实际成果汇总所选每幅影像的地类面积和占比；保留样区口径及实际重叠范围。",
        "确认上游分类图已入库，提供当前项目大屏与地理工作台入口，使用真实资源与任务引用。",
        "简洁交付所有选定影像的分类成果、统计与模型依据。",
    ]
    nodes = []
    for index, ((key, title), description, instruction) in enumerate(
        zip(titles, descriptions, instructions)
    ):
        row = {
            "id": key,
            "title": title,
            "kind": "operator"
            if key == "interpret"
            else "result"
            if key == "finish"
            else "agent",
            "description": description,
            "instruction": instruction,
            "dependsOn": [titles[index - 1][0]] if index else [],
            "dataRoles": ["image"] if index < 3 else [],
            "review": {"ai": False, "human": False, "maxRevisions": 0},
        }
        if key == "interpret":
            row.update(
                algorithmVersionId=version_id,
                parameters={"classes": "all"},
                contract={
                    "goal": instruction,
                    "acceptance": [
                        "每幅所选影像均有真实成功分类图和面积统计",
                        "分类图已通过标准质量检查并入库",
                    ],
                    "requiredOutputs": [
                        {"name": "classification", "semanticType": "raster"},
                        {"name": "statistics", "semanticType": "table"},
                    ],
                    "tools": [
                        "operator_catalog",
                        "preflight_operator",
                        "run_operator",
                        "read_evidence",
                        "read_task_record",
                        "ask_user",
                        "finish_node",
                    ],
                    "maxSteps": 96,
                    "maxModelCalls": 64,
                    "maxOperatorCalls": 8,
                    "maxRecoveries": 2,
                    "maxSeconds": 7200,
                    "sourceCoverage": {
                        "inputRole": "image",
                        "outputKey": "classification",
                    },
                    "importOutputs": ["classification"],
                },
            )
        nodes.append(row)
    return {
        "schemaVersion": 1,
        "adapter": "research_flow",
        "executionMode": "main_agent",
        "skill": default_skill("research_flow"),
        "inputRequirements": [
            {
                "key": "image",
                "label": "原始RGB影像",
                "description": "本项目已登记的2米Byte三波段RGB原始GeoTIFF，可选择一个或多个样区。",
                "dataTypes": ["raster"],
                "required": True,
                "requiredFields": [],
                "multiple": True,
            }
        ],
        "nodes": nodes,
        "outputRequirements": [
            "所选每幅影像的分类图",
            "实际类别面积统计",
            "同一智能体会话与处理记录",
        ],
    }
