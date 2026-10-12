from app.schemas.agent import FinishAnswer
from app.tools.runner import TOOLS


DESCRIPTIONS = {
    "get_grade_summary": (
        "查询指定学年的指定学期百分制成绩汇总。"
        "返回简单平均分、中位数、分数段、较低成绩课程"
        "以及排除记录数量。"
        "不计算学分加权平均分或GPA。"
    ),
    "compare_terms": (
        "比较两个指定学期的百分制成绩汇总。"
        "差值为第二个学期减第一个学期。"
        "不同学期课程可能不同，差值不能直接证明能力变化。"
    ),
    "get_schedule": (
        "查询指定学年、学期、教学周的课程安排。"
        "可限定星期，星期使用1至7。"
        "使用该用户该学期最新课表快照。"
        "当前不能直接把日期转换成教学周。"
    ),
    "get_degree_progress": (
        "查询当前用户最新培养计划快照的各类别学分进度。"
        "平台认定的获得学分是依据。"
        "父子节点不能重复相加，不能直接判定所有毕业条件。"
    ),
}


def build_tool_definitions():
    definitions = []

    for name, spec in TOOLS.items():
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": DESCRIPTIONS[name],
                    "parameters": (
                        spec.params_model.model_json_schema()
                    ),
                    "strict": False,
                },
            }
        )

    definitions.append(
        {
            "type": "function",
            "function": {
                "name": "finish_answer",
                "description": (
                    "完成本次回答，或请求用户补充必要信息。"
                    "回答个人数据问题时，必须引用成功工具结果。"
                ),
                "parameters": FinishAnswer.model_json_schema(),
                "strict": False,
            },
        }
    )

    return definitions