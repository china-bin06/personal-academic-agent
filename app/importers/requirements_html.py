from bs4 import BeautifulSoup

from app.schemas.requirement import (
    RequirementCourseInput,
    RequirementNodeInput,
)


EXPECTED_HEADERS = [
    "修读状态",
    "成绩学年",
    "学期",
    "课程号",
    "",
    "课程名称",
    "学时",
    "课程性质",
    "学分",
    "课程类别",
    "最大成绩",
    "绩点",
    "成绩",
    "补考",
    "重修",
    "建议修读学年",
    "学期",
    "课程重要性系数",
]

# 部分类别不显示建议修读学年和学期。
SHORT_HEADERS = (
    EXPECTED_HEADERS[:15]
    + [EXPECTED_HEADERS[-1]]
)

def text_of(tag) -> str:
    if tag is None:
        return ""

    return tag.get_text(" ", strip=True)


def parse_count(paragraph, font_name):
    tag = paragraph.find("font", attrs={"name": font_name})

    if tag is None:
        return None

    return int(text_of(tag))


def parse_courses(container):
    if container is None:
        return []

    table = container.find("table")

    if table is None:
        return []

    headers = [
        text_of(th)
        for th in table.select("thead th")
    ]

    if headers not in (EXPECTED_HEADERS, SHORT_HEADERS):
        container_id = container.get("id", "未知")

        raise ValueError(
            f"课程表头不一致，容器={container_id}\n"
            f"预期列数={len(EXPECTED_HEADERS)}，"
            f"实际列数={len(headers)}\n"
            f"预期表头={EXPECTED_HEADERS!r}\n"
            f"实际表头={headers!r}"
        )

    result = []

    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        values = [text_of(cell) for cell in cells]

        if len(values) != len(headers):
            raise ValueError(
                f"课程行列数不正确："
                f"表头{len(headers)}列，数据{len(values)}列"
            )

        status_tag = cells[0].find(attrs={"title": True})

        result.append(
            RequirementCourseInput(
                source_course_id=row.get("kch_id", ""),
                course_code=values[3],
                course_name=values[5],
                credits=values[8],
                study_status=(
                    status_tag.get("title", "")
                    if status_tag is not None
                    else values[0]
                ),
                raw_cells=values,
            )
        )

    return result


def parse_requirements_html(html: str):
    soup = BeautifulSoup(html, "html.parser")

    roots = []

    for li in soup.find_all("li"):
        title = li.find("div", class_="title", recursive=False)

        if title is None:
            continue

        paragraph = title.find("p", class_="title1")

        if paragraph is None:
            continue

        own_text = " ".join(
            str(value).strip()
            for value in paragraph.find_all(
                string=True,
                recursive=False,
            )
        ).strip()

        if own_text == "主修":
            roots.append(li)

    if len(roots) != 1:
        raise ValueError("需要包含且仅包含一个“主修”根节点")

    nodes = []

    def walk(li, parent_id=None):
        title = li.find("div", class_="title", recursive=False)

        if title is None:
            raise ValueError("节点缺少直接所属的title区域")

        paragraph = title.find("p", class_="title1")

        if paragraph is None:
            raise ValueError("节点缺少标题")

        node_id = title.get("xfyqjd_id") or li.get("xfyqjd_id")

        if not node_id:
            raise ValueError("节点缺少平台标识")

        declared_parent = li.get("fxfyqjd_id") or None

        if declared_parent != parent_id:
            raise ValueError(
                f"节点{node_id}的嵌套关系与父标识不一致"
            )

        own_text = " ".join(
            str(value).strip()
            for value in paragraph.find_all(
                string=True,
                recursive=False,
            )
        ).strip()

        name = own_text.split("要求学分", 1)[0].strip()

        courses_container = li.find(
            "div",
            id=f"kcxx{node_id}",
            recursive=False,
        )

        courses = parse_courses(courses_container)

        expected_count = parse_count(paragraph, "zms")
        passed_count = parse_count(paragraph, "yxmc")

        if expected_count is not None:
            if len(courses) != expected_count:
                raise ValueError(
                    f"{name}显示{expected_count}门课程，"
                    f"HTML实际只有{len(courses)}门；"
                    "请展开课程列表后重新获取HTML"
                )

        if title.get("sfmjd") == "1" and expected_count is None:
            raise ValueError(
                f"{name}缺少课程数量，无法确认明细是否完整"
            )

        if (
            passed_count is not None
            and expected_count is not None
            and passed_count > expected_count
        ):
            raise ValueError(f"{name}的通过数量大于课程总数")

        relation = None

        if li.has_attr("并且"):
            relation = "并且"
        elif li.has_attr("或者"):
            relation = "或者"

        nodes.append(
            RequirementNodeInput(
                source_node_id=node_id,
                parent_source_id=parent_id,
                name=name,
                required_credits=paragraph.get("yqzdxf"),
                earned_credits=paragraph.get("yxxf"),
                completion_raw=paragraph.get("sftg"),
                relation_raw=relation,
                expected_course_count=expected_count,
                passed_course_count=passed_count,
                courses=courses,
            )
        )

        children = li.find("ul", recursive=False)

        if children is not None:
            for child in children.find_all(
                "li",
                recursive=False,
            ):
                walk(child, node_id)

    walk(roots[0])

    ids = [node.source_node_id for node in nodes]

    if len(ids) != len(set(ids)):
        raise ValueError("同一HTML中出现重复节点标识")

    return nodes