import json

from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="msedge",
            headless=False,
        )

        try:
            context = browser.new_context(
                storage_state="playwright/.auth/jwxt.json"
            )

            page = context.new_page()

            page.goto(
                "https://jwxt.scnu.edu.cn/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )

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

            grades_page.wait_for_load_state(
                "domcontentloaded"
            )

            print(
                "请确认成绩查询页面正常显示。"
                "先不要操作导出，点击 Inspector 的 Resume，"
                "打印筛选控件信息。"
            )

            grades_page.pause()

            controls = grades_page.evaluate(
                """
                () => {
                    const elements = document.querySelectorAll("select");
                    const result = [];

                    for (let i = 0; i < elements.length; i++) {
                        const element = elements[i];
                        const options = [];

                        for (let j = 0; j < element.options.length; j++) {
                            const option = element.options[j];

                            options.push({
                                value: option.value,
                                text: (option.textContent || "").trim(),
                                selected: option.selected
                            });
                        }

                        result.push({
                            id: element.id,
                            name: element.name,
                            className: element.className,
                            value: element.value,
                            options: options
                        });
                    }

                    return result;
                }
                """
            )

            print("下拉控件信息：")
            print(
                json.dumps(
                    controls,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            print(
                "接下来可以手动选择目标学期、查询，"
                "点击第一步导出按钮。"
                "先不要点击最终下载按钮，"
                "查看并复制它的 outerHTML。"
                "检查完成后点击 Resume 退出。"
            )

            grades_page.pause()

        finally:
            browser.close()


if __name__ == "__main__":
    main()