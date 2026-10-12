"""仅供本地页面任务使用；复用CLI函数，不改变CLI的操作方式。"""
import argparse
import time
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright

from app.core.collection_log import CollectionTask
from app.importers.requirements_html import parse_requirements_html
from app.services import collection_control as control
from scripts import download_grades as grades
from scripts import download_schedule as schedule
from scripts.capture_requirements_page import PLAN_URL, expand_requirement_sections

HOME = "https://jwxt.scnu.edu.cn/"


def ready(page, kind):
    if page.is_closed() or not page.url.startswith(HOME):
        return False
    # 原生DOM检查，避免教务页面修改Array方法影响Playwright CSS引擎。
    return page.evaluate(r"""kind => {
        const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
        for (const e of document.querySelectorAll('input[type="password"]')) {
            if (visible(e)) return false;
        }
        if (kind === 'requirements') {
            return !!document.querySelector('li[xfyqjd_id]') && !!document.querySelector('[id^="showKc"]');
        }
        for (const e of document.querySelectorAll('button, [role="button"]')) {
            if (visible(e) && e.textContent.replace(/\s+/g, '') === '信息查询') return true;
        }
        return false;
    }""", kind)


def matching_page(context, kind):
    candidates = []
    for page in context.pages:
        if page.is_closed():
            continue
        if kind == "requirements" and page.url.split("?")[0] != PLAN_URL.split("?")[0]:
            continue
        if ready(page, kind):
            candidates.append(page)
    return candidates[0] if len(candidates) == 1 else None


def ensure_login(task_id, context, page, kind):
    target = matching_page(context, kind)
    if target:
        return target
    if kind == "requirements":
        # 直达计划被重定向时，让用户在首页登录，继续后自动进入计划。
        page.goto(HOME, wait_until="domcontentloaded", timeout=30_000)
    message = "请在新开的Edge完成登录，保留一个教务首页或目标培养计划标签页，再点击本页面的继续采集。无需Inspector。"
    while True:
        control.checkpoint(task_id)
        control.update(task_id, status="waiting_login", stage="authentication",
                       message=message)
        while not control.consume_continue(task_id):
            control.checkpoint(task_id)
            if not any(not p.is_closed() for p in context.pages):
                raise RuntimeError("browser closed")
            # Playwright等待同时处理浏览器事件。
            next(p for p in context.pages if not p.is_closed()).wait_for_timeout(400)
        control.checkpoint(task_id)
        control.update(task_id, status="running", stage="authentication",
                       message="已收到继续采集请求，正在检查已打开的教务页面。")
        target = matching_page(context, kind)
        if not target and kind == "requirements":
            home = matching_page(context, "home")
            if home:
                home.goto(PLAN_URL, wait_until="domcontentloaded", timeout=30_000)
                home.wait_for_timeout(800)
                target = matching_page(context, kind)
        if target:
            return target
        message = "已收到继续请求，但尚未唯一识别到已登录的教务首页或培养计划。请等待页面加载完成，保留一个目标标签页后再点击继续采集。"


def step(task, stage, message):
    control.checkpoint(task.task_id)
    task.stage = stage
    control.update(task.task_id, status="running", stage=stage, message=message)


def run_collection(task):
    auth = control.ROOT / "playwright/.auth/jwxt.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=False)
        try:
            kwargs = {"accept_downloads": True}
            if auth.is_file():
                kwargs["storage_state"] = str(auth)
            try:
                context = browser.new_context(**kwargs)
            except Exception:
                # 损坏的本地认证文件也允许重新手动登录。
                context = browser.new_context(accept_downloads=True)
            context.set_default_timeout(15_000)
            step(task, "authentication", "正在检查登录状态，必要时请在Edge登录。")
            page = context.new_page()
            page.goto(PLAN_URL if task.data_type == "requirements" else HOME,
                      wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(800)
            page = ensure_login(task.task_id, context, page, task.data_type)
            control.checkpoint(task.task_id)
            context.storage_state(path=str(auth))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            if task.data_type == "requirements":
                step(task, "expand_sections", "正在展开培养计划并检查课程数量。")
                expand_requirement_sections(page)
                step(task, "save_raw", "正在保存培养计划HTML。")
                target = control.ROOT / "data/raw/web" / f"requirements-{stamp}.html"
                target.parent.mkdir(parents=True, exist_ok=True)
                html = page.content()
                target.write_text(html, encoding="utf-8")
                task.attach_file(target)
                step(task, "validate_file", "正在校验培养计划完整树。")
                nodes = parse_requirements_html(html)
                counts = {"requirement_nodes": len(nodes), "course_entries": sum(len(n.courses) for n in nodes)}
            else:
                step(task, "browser_navigation", "正在进入目标查询页面。")
                page.get_by_role("button", name="信息查询", exact=True).click()
                with page.expect_popup(timeout=30_000) as popup:
                    if task.data_type == "grades":
                        page.get_by_role("link", name="学生成绩查询", exact=True).click()
                    else:
                        page.locator("xpath=//a[normalize-space(.)='个人课表查询' and contains(@onclick, \"clickMenu('N2151',\") and contains(@onclick, '/kbcx/xskbcx_cxXskbcxIndex.html')]").click()
                page = popup.value
                page.wait_for_function("""() => {
                    const y = document.getElementById('xnm'), s = document.getElementById('xqm');
                    return y && s && y.options.length > 1 && s.options.length > 1;
                }""", timeout=30_000)
                step(task, "set_filters", "正在设置学年学期。")
                if task.data_type == "grades":
                    grades.set_filters(page, task.academic_year, task.semester)
                    step(task, "query", "正在查询成绩并等待结果刷新。")
                    grades.query_grades(page, task.academic_year, task.semester)
                    step(task, "export", "正在导出Excel。")
                    page.get_by_role("button", name=grades.re.compile(r"导出\s*$")).click()
                    option = page.locator("xpath=//input[@type='radio' and @name='exportWjgs' and @value='xls']")
                    option.check()
                    if not option.is_checked():
                        raise ValueError("Excel option")
                    button = page.locator("xpath=//button[@id='btn_bcdc']")
                    suffix, folder = ".xlsx", "grades"
                else:
                    schedule.set_schedule_filters(page, task.academic_year, task.semester)
                    step(task, "query", "正在查询课表并等待标题校验。")
                    schedule.query_schedule(page, task.academic_year, task.semester)
                    step(task, "export", "正在导出课表PDF。")
                    button = page.locator("xpath=//button[@id='shcPDF']")
                    suffix, folder = ".pdf", "pdf"
                with page.expect_download(timeout=60_000) as downloading:
                    button.click()
                download = downloading.value
                if Path(download.suggested_filename).suffix.lower() != suffix:
                    raise ValueError("download format")
                step(task, "download", "正在保存原始文件。")
                target = control.ROOT / "data/raw" / folder / f"{task.data_type}-{task.academic_year}-{task.semester}-{stamp}{suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(target))
                task.attach_file(target)
                step(task, "validate_file", "正在校验文件内容与请求学期。")
                validate = grades.validate_download if task.data_type == "grades" else schedule.validate_schedule_pdf
                counts = validate(target, task.academic_year, task.semester)
            task.mark_validated(counts)
            control.checkpoint(task.task_id)
            return target
        finally:
            browser.close()


def execute(task_id):
    state = control.get_task(task_id)
    task = CollectionTask(state["data_type"])
    task.task_id = task_id
    task.started_at = state["started_at"]
    task.set_term(state["academic_year"], state["semester"])
    try:
        task.write("started")
        target = run_collection(task)
        control.checkpoint(task_id)
        task.write("validated")
        control.update(task_id, status="completed", stage="validated", raw_file=target.relative_to(control.ROOT).as_posix(),
                       message="采集与文件校验完成，尚未入库。请查看预览并确认导入。")
    except control.Cancelled:
        control.update(task_id, status="cancelled", message="采集已取消，未导入数据库。")
        task.write("cancelled")
    except Exception as error:
        control.update(task_id, status="failed", error_type=type(error).__name__,
                       message=f"采集失败，阶段={task.stage}。请检查登录、页面结构或学期是否有数据；未导入数据库。")
        task.write("failed", type(error).__name__)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    execute(parser.parse_args().task_id)
