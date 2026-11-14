"""Use the common source/packaging/trial/publication gate for native observations."""

from apps.business_flows.wildfire import CODE, definition
from .register_spartina import Command as RegisterCommand


class Command(RegisterCommand):
    help = "登记野火原生观测算子、试运行和项目业务流"
    source_folder = "wildfire-observe"
    flow_code = CODE
    flow_title = "野火历史观测制图"
    flow_description = "选择真实时期和研究区，从原生SeasFire生成观测原值、面积分级、区域统计与历史序列。"
    algorithm_category = "野火观测制图"
    scene = "wildfire"
    default_inputs = {"cube": 1475}
    default_parameters = {
        "product": "gwis_ba",
        "time_index": 873,
        "history": 12,
        "west": 112,
        "south": -44,
        "east": 154,
        "north": -10,
    }
    build_definition = staticmethod(definition)
