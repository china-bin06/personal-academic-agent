import argparse
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.importers.grades_excel import parse_grades_excel

from app.core.collection_log import (
    collection_task,
    reject_visible_login_form,
)

SEMESTER_VALUES = {
    1: "3",
    2: "12",
    3: "16",
}


def set_filters(page, academic_year, semester):
    year_value = academic_year.split("-")[0]
    semester_value = SEMESTER_VALUES[semester]

    selected = page.evaluate(
        """
        values => {
            function setSelect(id, value) {
                const element = document.getElementById(id);

                if (!element) {
                    throw new Error("找不到筛选控件：" + id);
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
                        "控件没有目标选项：" + id + "=" + value
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
                semester: setSelect("xqm", values.semester),
                course_flag: setSelect("kcbjdm_cx", "")
            };
        }
        """,
        {
            "year": year_value,
            "semester": semester_value,
        },
    )

    if (
        selected["year"] != year_value
        or selected["semester"] != semester_value
        or selected["course_flag"] != ""
    ):
        raise ValueError("筛选条件设置失败")

    print(
        f"已设置查询条件：{academic_year}"
        f" 第{semester}学期，课程标记=全部"
    )


def validate_download(path, academic_year, semester):
    records, errors = parse_grades_excel(path)

    if errors:
        raise ValueError(
            f"下载文件存在{len(errors)}条解析错误，"
            "请使用 import_grades --preview 查看详情"
        )

    if not records:
        raise ValueError("下载文件没有成绩记录")

    actual_terms = {
        (record.academic_year, record.semester)
        for record in records
    }

    expected_terms = {(academic_year, semester)}

    if actual_terms != expected_terms:
        raise ValueError(
            f"下载文件学期不一致："
            f"预期={expected_terms}，实际={actual_terms}"
        )

    print(f"文件解析通过：{len(records)}条成绩记录")
    print("文件内容中的学年、学期与请求一致")

    return {"grade_records": len(records)}


def query_grades(page, academic_year, semester):
    # 等待表格初始化，并等待之前的加载结束
    page.wait_for_function(
        """
        () => {
            const table = document.getElementById("tabGrid");
            const loading = document.getElementById("load_tabGrid");

            return table && table.grid && loading
                && (
                    getComputedStyle(loading).display === "none"
                    || loading.getClientRects().length === 0
                );
        }
        """,
        timeout=30_000,
    )

    # 必须在点击查询之前注册完成事件
    page.evaluate(
        """
        () => {
            if (typeof window.jQuery !== "function") {
                throw new Error("页面没有找到jQuery");
            }

            const table = document.getElementById("tabGrid");

            window.__academicGradeQuery = {
                completed: false,
                failed: false
            };

            const grid = window.jQuery(table);

            grid.off(".academicAgent");

            grid.on(
                "jqGridLoadComplete.academicAgent",
                function () {
                    window.__academicGradeQuery.completed = true;
                }
            );

            grid.on(
                "jqGridLoadError.academicAgent",
                function () {
                    window.__academicGradeQuery.failed = true;
                }
            );
        }
        """
    )

    page.locator(
        "xpath=//button[@id='search_go']"
    ).click(timeout=15_000)

    page.wait_for_function(
        """
        () => {
            const state = window.__academicGradeQuery;

            if (!state) {
                return false;
            }

            if (state.failed) {
                throw new Error("成绩查询请求失败");
            }

            const loading = document.getElementById("load_tabGrid");

            if (!loading) {
                return false;
            }

            const hidden = (
                getComputedStyle(loading).display === "none"
                || loading.getClientRects().length === 0
            );

            return state.completed && hidden;
        }
        """,
        timeout=30_000,
    )

    # 直接读取DOM，避开之前出错的CSS Locator路径
    result = page.evaluate(
        """
        target => {
            const table = document.getElementById("tabGrid");
            const rows = table.querySelectorAll("tr.jqgrow");

            if (rows.length === 0) {
                return {count: 0, termMatches: true};
            }

            for (let i = 0; i < rows.length; i++) {
                const year = rows[i].querySelector(
                    'td[aria-describedby="tabGrid_xnmmc"]'
                );

                const semester = rows[i].querySelector(
                    'td[aria-describedby="tabGrid_xqmmc"]'
                );

                if (
                    !year || !semester
                    || year.textContent.trim() !== target.year
                    || semester.textContent.trim() !== target.semester
                ) {
                    return {
                        count: rows.length,
                        termMatches: false
                    };
                }
            }

            return {
                count: rows.length,
                termMatches: true
            };
        }
        """,
        {
            "year": academic_year,
            "semester": str(semester),
        },
    )

    if result["count"] == 0:
        raise ValueError(
            "查询已完成，但没有成绩记录，停止导出"
        )

    if not result["termMatches"]:
        raise ValueError(
            "查询结果中的学年或学期不一致，停止导出"
        )

    print(
        f"查询完成：当前页{result['count']}条记录，"
        f"均属于{academic_year}第{semester}学期"
    )


@collection_task("grades")
def main(task):
    parser = argparse.ArgumentParser(
        description="下载指定学期成绩并校验，不写数据库"
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
        default="data/raw/grades",
    )

    args = parser.parse_args()

    task.set_term(args.academic_year, args.semester)
    
    if not re.fullmatch(r"\d{4}-\d{4}", args.academic_year):
        raise SystemExit("学年格式应为2025-2026")

    start_year, end_year = map(
        int,
        args.academic_year.split("-"),
    )

    if end_year != start_year + 1:
        raise SystemExit("学年必须为连续两年")

    task.stage = "authentication"

    auth_path = Path("playwright/.auth/jwxt.json")

    if not auth_path.is_file():
        raise SystemExit(
            "登录状态文件不存在，"
            "请先运行培养计划采集脚本完成登录"
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
                page.get_by_role(
                    "link",
                    name="学生成绩查询",
                    exact=True,
                ).click()

            grades_page = popup_info.value

            grades_page.wait_for_function(
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

            set_filters(
                grades_page,
                args.academic_year,
                args.semester,
            )

            task.stage = "query"

            query_grades(
                grades_page,
                args.academic_year,
                args.semester,
            )

            task.stage = "export"

            grades_page.get_by_role(
                "button",
                name=re.compile(r"导出\s*$"),
            ).click()

            excel_option = grades_page.locator(
                "xpath=//input[@type='radio' "
                "and @name='exportWjgs' "
                "and @value='xls']"
            )

            excel_option.wait_for(
                state="visible",
                timeout=15_000,
            )

            excel_option.check(timeout=15_000)

            if not excel_option.is_checked():
                raise ValueError("未能选中Excel导出格式")

            print("已确认Excel导出格式")

            final_button = grades_page.locator(
                "xpath=//button[@id='btn_bcdc']"
            )

            with grades_page.expect_download(
                timeout=60_000
            ) as download_info:
                final_button.click(timeout=15_000)

            download = download_info.value

            suffix = Path(
                download.suggested_filename
            ).suffix.lower()

            if suffix != ".xlsx":
                raise ValueError(
                    "下载格式不是.xlsx："
                    f"{suffix or '无扩展名'}。"
                    "请确认导出格式选择的是Excel，"
                    "当前解析器仅支持.xlsx"
                )

            stamp = datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )

            target = output_dir / (
                f"grades-{args.academic_year}-"
                f"{args.semester}-{stamp}.xlsx"
            )

            task.stage = "download"

            download.save_as(str(target))
            task.attach_file(target)
            print(f"已保存下载文件：{target}")

            task.stage = "validate_file"

            counts = validate_download(
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
