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
                page.locator(
                    "xpath=//a["
                    "normalize-space(.)='个人课表查询' "
                    "and contains(@onclick, \"clickMenu('N2151',\") "
                    "and contains(@onclick, "
                    "'/kbcx/xskbcx_cxXskbcxIndex.html')"
                    "]"
                ).click(timeout=15_000)

            schedule_page = popup_info.value

            schedule_page.wait_for_url(
                "**/kbcx/xskbcx_cxXskbcxIndex.html*",
                timeout=30_000,
            )

            schedule_page.wait_for_load_state(
                "domcontentloaded"
            )

            print(
                "请确认打开的是个人课表查询页面。\n"
                "等待学年、学期选项加载完成后，"
                "点击 Inspector 的 Resume。"
            )

            schedule_page.pause()

            controls = schedule_page.evaluate(
                """
                () => {
                    const elements = document.querySelectorAll(
                        "select"
                    );

                    const result = [];

                    for (let i = 0; i < elements.length; i++) {
                        const element = elements[i];
                        const options = [];

                        for (
                            let j = 0;
                            j < element.options.length;
                            j++
                        ) {
                            const option = element.options[j];

                            options.push({
                                value: option.value,
                                text: (
                                    option.textContent || ""
                                ).trim(),
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

            print("课表筛选控件：")
            print(
                json.dumps(
                    controls,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            print(
                "控件信息已打印。\n"
                "可继续查看页面；"
                "点击 Inspector 的 Resume 后退出。"
            )

            schedule_page.pause()

        finally:
            browser.close()


if __name__ == "__main__":
    main()