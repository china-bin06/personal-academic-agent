from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    expect,
    sync_playwright,
)

from app.core.collection_log import (
    collection_task,
    reject_visible_login_form,
)
from app.importers.requirements_html import parse_requirements_html


PLAN_URL = (
    "https://jwxt.scnu.edu.cn/xsxy/"
    "xsxyqk_cxXsxyqkIndex.html"
    "?gnmkdm=N105515&layout=default"
)


def wait_for_requirement_courses(
    section,
    container,
    node_id,
):
    count_label = section.locator('font[name="zms"]')

    if count_label.count() != 1:
        raise ValueError(
            f"无法唯一定位课程总数：{node_id}"
        )

    count_text = count_label.inner_text().strip()

    if not count_text.isdigit():
        raise ValueError(
            f"课程总数不是非负整数："
            f"{node_id}，内容={count_text!r}"
        )

    expected_count = int(count_text)

    # 只统计课程行，不包含表头
    course_rows = container.locator(
        "table.table tr[kch_id]"
    )

    try:
        expect(course_rows).to_have_count(
            expected_count,
            timeout=20_000,
        )
    except AssertionError:
        raise ValueError(
            f"课程加载不完整：{node_id}，"
            f"预期={expected_count}，"
            f"实际={course_rows.count()}"
        ) from None

    print(
        f"课程数量检查通过：{node_id}"
        f" | 预期={expected_count}"
        f" | 实际={course_rows.count()}"
    )


def expand_requirement_sections(page):
    all_sections = page.locator('span[id^="showKc"]')

    all_sections.first.wait_for(
        state="attached",
        timeout=15_000,
    )

    empty_ids = []

    # 检查无按钮区域，但不假定它们是父类别
    for index in range(all_sections.count()):
        section = all_sections.nth(index)
        section_id = section.get_attribute("id")

        if not section_id:
            raise ValueError("课程区域缺少ID")

        button_count = section.locator("a.more").count()

        if button_count == 1:
            continue

        if button_count > 1:
            raise ValueError(
                f"课程区域存在多个展开按钮：{section_id}"
            )

        node_id = section_id.removeprefix("showKc")
        container = page.locator(
            f'[id="kcxx{node_id}"]'
        )

        if container.count() != 1:
            raise ValueError(
                f"课程容器无法唯一定位：{node_id}"
            )

        row_count = container.locator(
            "table.table tr[kch_id]"
        ).count()

        # 只跳过已观察到的“空按钮占位+空课程容器”
        if section.inner_text().strip() or row_count != 0:
            raise ValueError(
                f"无按钮区域存在内容，需要检查："
                f"{section_id}，课程行数={row_count}"
            )

        empty_ids.append(section_id)
        print(f"空占位区域，不执行点击：{section_id}")

    sections = page.locator(
        'span[id^="showKc"]:has(a.more)'
    )

    count = sections.count()

    if count == 0:
        raise ValueError("未找到实际课程展开按钮")

    print(f"发现 {count} 个实际课程展开区域")

    for index in range(count):
        section = sections.nth(index)
        section_id = section.get_attribute("id")
        node_id = section_id.removeprefix("showKc")

        container = page.locator(
            f'[id="kcxx{node_id}"]'
        )

        if container.count() != 1:
            raise ValueError(
                f"课程容器无法唯一定位：{node_id}"
            )

        button = section.locator("a.more")

        if button.count() != 1:
            raise ValueError(
                f"展开按钮无法唯一定位：{section_id}"
            )

        if not container.is_visible():
            if not button.is_visible():
                raise ValueError(
                    f"展开按钮不可见：{section_id}"
                )

            button.click(timeout=10_000)

            container.wait_for(
                state="visible",
                timeout=15_000,
            )

            print(f"已展开：{node_id}")
        else:
            print(f"保持已展开：{node_id}")

        wait_for_requirement_courses(
            section,
            container,
            node_id,
        )

    if sections.count() != count:
        raise ValueError(
            "课程展开区域数量发生变化，页面可能仍在加载"
        )

    # 复查所有有按钮的区域
    for index in range(count):
        section = sections.nth(index)
        section_id = section.get_attribute("id")
        node_id = section_id.removeprefix("showKc")

        container = page.locator(
            f'[id="kcxx{node_id}"]'
        )

        if not container.is_visible():
            raise ValueError(
                f"课程区域被收起：{node_id}"
            )

        wait_for_requirement_courses(
            section,
            container,
            node_id,
        )

    # 空占位若后来出现内容，拒绝按原判断继续保存
    for section_id in empty_ids:
        section = page.locator(
            f'[id="{section_id}"]'
        )

        node_id = section_id.removeprefix("showKc")
        container = page.locator(
            f'[id="kcxx{node_id}"]'
        )

        if (
            section.inner_text().strip()
            or container.locator(
                "table.table tr[kch_id]"
            ).count() != 0
        ):
            raise ValueError(
                f"空占位区域后来出现内容，需要重新采集："
                f"{section_id}"
            )

    print("有按钮的课程区域展开及数量检查通过")
    print(
        f"空占位区域共 {len(empty_ids)} 个，"
        "已保留在HTML中，尚需核对"
    )


@collection_task("requirements")
def main(task):
    output_dir = Path("data/raw/web")
    auth_dir = Path("playwright/.auth")

    output_dir.mkdir(parents=True, exist_ok=True)
    auth_dir.mkdir(parents=True, exist_ok=True)

    auth_path = auth_dir / "jwxt.json"

    task.stage = "browser_navigation"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="msedge",
            headless=False,
        )

        try:
            if auth_path.exists():
                print("使用已保存的登录状态")
                context = browser.new_context(
                    storage_state=str(auth_path)
                )
            else:
                print("没有登录状态，需要手动登录")
                context = browser.new_context()

            page = context.new_page()

            page.goto(
                PLAN_URL,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            task.stage = "authentication"

            print(
                "请检查培养计划是否正常显示。\n"
                "如需登录，请手动登录并进入培养计划。\n"
                "这次不要手动展开课程区域。\n"
                "确认页面正常后，点击 Inspector 的 Resume。"
            )

            page.pause()

            # 手动登录或导航可能打开新的标签页
            plan_pages = [
                opened_page
                for opened_page in context.pages
                if not opened_page.is_closed()
                and opened_page.url.split("?")[0] == (
                    "https://jwxt.scnu.edu.cn/xsxy/"
                    "xsxyqk_cxXsxyqkIndex.html"
                )
            ]

            if len(plan_pages) != 1:
                raise ValueError(
                    "无法唯一确定培养计划标签页；"
                    "请确认只打开一个目标页面"
                )

            plan_page = plan_pages[0]

            reject_visible_login_form(plan_page)

            task.stage = "expand_sections"

            expand_requirement_sections(plan_page)

            stamp = datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )

            target = output_dir / (
                f"requirements-{stamp}.html"
            )

            # 保存原始文件不代表完整树校验成功。
            task.stage = "save_raw"
            html = plan_page.content()

            target.write_text(
                html,
                encoding="utf-8",
            )

            task.attach_file(target)

            task.stage = "validate_file"
            nodes = parse_requirements_html(html)

            task.mark_validated({
                "requirement_nodes": len(nodes),
                "course_entries": sum(
                    len(node.courses) for node in nodes
                ),
            })

            context.storage_state(
                path=str(auth_path)
            )

            print(f"已保存培养计划：{target}")
            print("已更新本地登录状态")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
