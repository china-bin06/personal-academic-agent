import argparse
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.core.collection_log import (
    collection_task,
    reject_visible_login_form,
)
from scripts.extract_schedule_blocks import extract_blocks
from scripts.normalize_schedule_blocks import (
    parse_other,
    parse_scheduled,
)


SEMESTER_VALUES = {
    1: "3",
    2: "12",
    3: "16",
}


def set_schedule_filters(page, academic_year, semester):
    expected = {
        "year": academic_year.split("-")[0],
        "semester": SEMESTER_VALUES[semester],
    }

    actual = page.evaluate(
        """
        values => {
            function setSelect(id, value) {
                const element = document.getElementById(id);

                if (!element) {
                    throw new Error("找不到控件：" + id);
                }

                let found = false;

                for (let i = 0; i < element.options.length; i++) {
                    if (element.options[i].value === value) {
                        found = true;
                        break;
                    }
                }

                if (!found) {
                    throw new Error(
                        "找不到目标选项：" + id + "=" + value
                    );
                }

                element.value = value;

                if (typeof window.jQuery === "function") {
                    window.jQuery(element).trigger("change");
                    window.jQuery(element).trigger("chosen:updated");
                } else {
                    element.dispatchEvent(
                        new Event("change", {bubbles: true})
                    );
                }

                return element.value;
            }

            return {
                year: setSelect("xnm", values.year),
                semester: setSelect("xqm", values.semester)
            };
        }
        """,
        expected,
    )

    if actual != expected:
        raise ValueError("课表筛选条件设置失败")

    print(
        f"已设置：{academic_year}第{semester}学期"
    )



def query_schedule(page, academic_year, semester):
    expected_title = (
        f"{academic_year}学年第{semester}学期"
    )

    # 先监听结果区域，再点击查询，避免接受旧课表。
    page.evaluate(
        """
        () => {
            const root = document.getElementById("ylkbTable");

            if (!root) {
                throw new Error("找不到课表结果区域：ylkbTable");
            }

            const previous = window.__academicScheduleWatch;
            if (previous) {
                previous.observer.disconnect();
            }

            const state = {
                changed: false,
                lastChange: 0,
                observer: null
            };

            state.observer = new MutationObserver(() => {
                state.changed = true;
                state.lastChange = performance.now();
            });

            state.observer.observe(root, {
                childList: true,
                subtree: true,
                characterData: true
            });

            window.__academicScheduleWatch = state;
        }
        """
    )

    try:
        page.locator(
            "xpath=//button[@id='search_go']"
        ).click(timeout=15_000)

        page.wait_for_function(
            """
            expectedTitle => {
                const state = window.__academicScheduleWatch;

                if (!state || !state.changed) {
                    return false;
                }

                const table = document.getElementById(
                    "kbgrid_table_0"
                );

                if (!table || table.getClientRects().length === 0) {
                    return false;
                }

                const title = table.querySelector(
                    ".timetable_title h6.pull-left"
                );

                if (!title) {
                    return false;
                }

                const actualTitle = title.textContent.replace(
                    /\\s+/g, ""
                );

                if (actualTitle !== expectedTitle) {
                    return false;
                }

                const button = document.getElementById("shcPDF");

                if (
                    !button
                    || button.disabled
                    || button.getAttribute("data-type") !== "table"
                ) {
                    return false;
                }

                // 等待结果区域短暂稳定，避免正在替换表格时导出。
                return performance.now() - state.lastChange >= 500;
            }
            """,
            arg=expected_title,
            timeout=30_000,
        )

        print(f"课表已刷新，标题校验通过：{expected_title}")

    finally:
        page.evaluate(
            """
            () => {
                const state = window.__academicScheduleWatch;

                if (state) {
                    state.observer.disconnect();
                    delete window.__academicScheduleWatch;
                }
            }
            """
        )


def validate_schedule_pdf(path, academic_year, semester):
    result = extract_blocks(path)

    if (
        result["academic_year"] != academic_year
        or result["semester"] != semester
    ):
        raise ValueError(
            "PDF实际学期与请求不一致："
            f"请求={academic_year}-{semester}，"
            f"实际={result['academic_year']}-"
            f"{result['semester']}"
        )

    block_count = len(result["scheduled_blocks"])
    other_count = len(result["other_courses"])

    if block_count == 0 and other_count == 0:
        raise ValueError("PDF未解析出任何课程")

    for index, block in enumerate(
        result["scheduled_blocks"], start=1
    ):
        try:
            parse_scheduled(block)
        except (ValueError, KeyError, TypeError) as error:
            print(
                f"课程块解析失败：第{index}块，"
                f"页码={block['source_pages']}，"
                f"星期={block['weekday']}，"
                f"错误类型={type(error).__name__}"
            )
            raise ValueError("课表课程块解析失败") from None

    for index, item in enumerate(
        result["other_courses"], start=1
    ):
        try:
            parse_other(item)
        except (ValueError, KeyError, TypeError) as error:
            print(
                f"其他课程解析失败：第{index}项，"
                f"页码={item['source_page']}，"
                f"错误类型={type(error).__name__}"
            )
            raise ValueError("其他课程解析失败") from None

    print("PDF实际学年、学期校验通过")
    print(f"有时间的课程块：{block_count}")
    print(f"其他课程：{other_count}")

    return {
        "scheduled_blocks": block_count,
        "other_courses": other_count,
    }


@collection_task("schedule")
def main(task):
    parser = argparse.ArgumentParser(
        description="下载课表PDF并校验，不写数据库"
    )

    parser.add_argument("--academic-year", required=True)
    parser.add_argument(
        "--semester",
        type=int,
        choices=[1, 2, 3],
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/pdf",
    )

    args = parser.parse_args()

    task.set_term(args.academic_year, args.semester)

    if not re.fullmatch(r"\d{4}-\d{4}", args.academic_year):
        raise SystemExit("学年格式应为2026-2027")

    start, end = map(int, args.academic_year.split("-"))

    if end != start + 1:
        raise SystemExit("学年必须为连续两年")

    task.stage = "authentication"
    auth_path = Path("playwright/.auth/jwxt.json")

    if not auth_path.is_file():
        raise SystemExit(
            "登录状态不存在，请先完成登录并保存状态"
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task.stage = "browser_navigation"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="msedge",
            headless=False,
        )

        try:
            context = browser.new_context(
                storage_state=str(auth_path),
                accept_downloads=True,
            )

            page = context.new_page()

            page.goto(
                "https://jwxt.scnu.edu.cn/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            task.stage = "authentication"
            reject_visible_login_form(page)
            task.stage = "browser_navigation"

            page.get_by_role(
                "button",
                name="信息查询",
                exact=True,
            ).click()

            with page.expect_popup() as popup_info:
                page.locator(
                    "xpath=//a["
                    "normalize-space(.)='个人课表查询' "
                    "and contains(@onclick, \"clickMenu('N2151',\") "
                    "and contains(@onclick, "
                    "'/kbcx/xskbcx_cxXskbcxIndex.html')"
                    "]"
                ).click(timeout=15_000)

            schedule_page = popup_info.value

            schedule_page.wait_for_function(
                """
                () => {
                    const year = document.getElementById("xnm");
                    const semester = document.getElementById("xqm");

                    return year && semester
                        && year.options.length > 1
                        && semester.options.length > 1;
                }
                """,
                timeout=30_000,
            )

            task.stage = "set_filters"

            set_schedule_filters(
                schedule_page,
                args.academic_year,
                args.semester,
            )

            task.stage = "query"

            query_schedule(
                schedule_page,
                args.academic_year,
                args.semester,
            )

            task.stage = "export"

            pdf_button = schedule_page.locator(
                "xpath=//button[@id='shcPDF']"
            )

            with schedule_page.expect_download(
                timeout=60_000
            ) as download_info:
                pdf_button.click(timeout=15_000)

            download = download_info.value

            suffix = Path(
                download.suggested_filename
            ).suffix.lower()

            if suffix != ".pdf":
                raise ValueError(
                    f"下载文件不是PDF：{suffix or '无扩展名'}"
                )

            stamp = datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )

            target = output_dir / (
                f"schedule-{args.academic_year}-"
                f"{args.semester}-{stamp}.pdf"
            )

            task.stage = "download"

            download.save_as(str(target))
            task.attach_file(target)
            print(f"已保存课表PDF：{target}")

            task.stage = "validate_file"

            counts = validate_schedule_pdf(
                target,
                args.academic_year,
                args.semester,
            )

            task.mark_validated(counts)

            print("下载及校验完成，未写入数据库")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
