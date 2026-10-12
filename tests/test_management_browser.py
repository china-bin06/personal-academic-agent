"""本地浏览器验收：使用虚构接口响应，不调用模型或写学业数据库。"""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def test_upload_confirm_tree_tasks_and_old_chat(tmp_path):
    root = Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/static/"):
                self.path = self.path.removeprefix("/static")
            super().do_GET()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "app/static")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors, confirms, calendar_state = [], [], {}
    node = {"node_id": "root", "parent_id": None, "name": "主修", "required_credits": "4",
            "earned_credits": "2", "children": [{"node_id": "child", "parent_id": "root",
            "name": "必修测试", "required_credits": "4", "earned_credits": "2", "children": [],
            "courses": [{"course_name": "培养计划明细测试课程", "course_code": "TEST01", "credits": "2", "study_status": "已修"}]}]}
    preview = {"preview_id": "a" * 32, "data_type": "schedule", "filename": "schedule.json",
        "sha256": "b" * 64, "expires_at": "2099-01-01T00:00:00Z", "summary": {"courses": 1},
        "warnings": [], "payload": {"courses": [{"course_name": "机器人测试课", "credits": "2",
            "meetings": [{"teaching_type": "理论", "weekday": 5, "period_start": 5, "period_end": 6,
            "weeks": [1, 3, 5], "location": "测试教室"}]}]}}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                def route_api(route):
                    path = route.request.url.split("/api/v1/")[-1].split("?")[0]
                    if path == "imports/preview":
                        assert route.request.method == "POST"
                        assert route.request.headers["x-file-name"] == "schedule.json"
                        data = preview
                    elif path.endswith("/confirm"):
                        confirms.append(path)
                        data = {"result": {"status": "created", "snapshot_id": 1},
                                "confirmed_at": "2026-10-12T00:00:00Z", "note": "导入已完成"}
                    elif path == "data/status":
                        data = {"items": [{"data_type": "schedule", "academic_year": "2026-2027",
                            "semester": 1, "snapshot_id": 1, "imported_at": "2026-10-12T00:00:00Z"}], "note": "数据库时间"}
                    elif path == "data/requirements":
                        data = {"tree": [node], "note": "父子学分不能相加"}
                    elif path == "collections/tasks":
                        data = {"items": [{"task_id": "c" * 32, "data_type": "schedule", "status": "failed",
                            "stage": "browser_navigation", "error_type": "TimeoutError"}], "note": "采集日志", "malformed_lines": 0}
                    elif path == "collections/jobs":
                        data = []
                    elif path == "calendar":
                        if route.request.method == "PUT": calendar_state.update(route.request.post_data_json, updated_at="2026-10-12T08:00:00+08:00")
                        data = {"current_time": "2026-10-12T08:00:00+08:00", "configuration": calendar_state or None, "note": "常规教学周"}
                    elif path == "chat":
                        data = {"status": "needs_clarification", "answer": "请明确周次", "warnings": [], "evidence": []}
                    else:
                        raise AssertionError(path)
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
                page.route("**/api/v1/**", route_api)
                page.route("**/health**", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok"}'))
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                expect(page.locator("#question-panel")).to_be_visible()
                for panel in ["import-panel", "data-panel", "calendar-panel", "plan-panel", "tasks-panel"]:
                    expect(page.locator(f"#{panel}")).to_be_hidden()
                assert page.locator("#question-panel #result").count() == 1
                expect(page.locator("#site-clock")).to_contain_text("2026")
                assert page.locator(".campus-illustration img").evaluate("e => e.complete && e.naturalWidth > 0")
                page.locator("#illustration-size").fill("300")
                assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--campus-width').trim()") == "300px"
                page.locator("#nav-plan").click()
                expect(page.locator("#plan-tree")).to_contain_text("必修测试")
                page.locator("#plan-tree summary").filter(has_text="课程明细").click()
                expect(page.locator("#plan-tree")).to_contain_text("培养计划明细测试课程")
                expect(page.locator("#plan-tree td").filter(has_text="TEST01")).to_be_visible()
                page.locator("#nav-tasks").click()
                expect(page.locator("#task-list")).to_contain_text("TimeoutError")
                page.locator("#nav-data").click()
                expect(page.locator("#data-status")).to_contain_text("2026-2027")
                expect(page.locator("#calendar-form")).to_be_hidden()
                assert page.locator("#data-panel #calendar-form").count() == 0
                page.locator("#nav-calendar").click()
                expect(page.locator("#calendar-panel")).to_be_visible()
                expect(page.locator("#data-panel")).to_be_hidden()
                page.locator("#calendar-year").fill("2026-2027")
                page.locator("#calendar-monday").fill("2026-09-07")
                page.on("dialog", lambda dialog: dialog.accept())
                page.locator("#calendar-save").click()
                expect(page.locator("#calendar-message")).to_contain_text("已同步：2026-2027")
                expect(page.locator("#calendar-message")).to_contain_text("保存时间：")
                assert calendar_state["first_monday"] == "2026-09-07"
                page.reload()
                expect(page.locator("#calendar-panel")).to_be_visible()
                expect(page.locator("#calendar-monday")).to_have_value("2026-09-07")
                page.go_back()
                expect(page.locator("#data-panel")).to_be_visible()
                page.go_back()
                expect(page.locator("#tasks-panel")).to_be_visible()
                page.locator("#nav-import").click()
                expect(page.locator("#manual-import-title")).to_have_text("手动导入")
                expect(page.locator("#auto-import-title")).to_have_text("自动导入")
                assert page.locator("#manual-import-panel #import-form").count() == 1
                assert page.locator("#auto-import-panel #collection-form").count() == 1
                assert page.locator("#tasks-panel form").count() == 0
                assert page.locator("#import-review #confirm-button").count() == 1
                assert page.locator("#confirm-button").is_disabled()
                page.locator("#import-type").select_option("schedule")
                file = tmp_path / "schedule.json"
                file.write_text("{}", encoding="utf-8")
                page.locator("#import-file").set_input_files(str(file))
                page.locator("#preview-button").click()
                expect(page.locator("#import-message")).to_contain_text("尚未入库")
                expect(page.locator("#import-preview")).to_contain_text("1、3、5")
                expect(page.locator("#import-preview")).to_contain_text("本次预览来源：手动导入")
                page.locator("#confirm-button").click()
                expect(page.locator("#import-message")).to_contain_text("新快照已创建")
                assert len(confirms) == 1
                assert page.locator("#confirm-button").is_disabled()
                page.locator("#nav-question").click()
                page.locator("#question-examples > summary").click()
                page.locator("#examples button").first.click()
                page.locator("#submit-button").click()
                expect(page.locator("#result-title")).to_have_text("需要补充信息")
                expect(page.locator("#warnings")).to_contain_text("重新提交完整问题")
                page.locator("#question-examples > summary").click()
                assert page.evaluate("document.getElementById('question-examples').compareDocumentPosition(document.getElementById('result')) & Node.DOCUMENT_POSITION_FOLLOWING")
                assert page.locator("#question-panel #result").is_visible()
                page.locator("#nav-import").click()
                page.locator("#nav-question").click()
                expect(page.locator("#result-title")).to_have_text("需要补充信息")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(tmp_path / "v2-mobile.png"), full_page=True)
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_page_collection_login_preview_cancel_and_restore():
    root = Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/static/"):
                self.path = self.path.removeprefix("/static")
            super().do_GET()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "app/static")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    jobs, starts, errors, confirms = [], [], [], []
    preview = {"preview_id": "a" * 32, "data_type": "schedule", "filename": "schedule.pdf",
        "expires_at": "2099-01-01T00:00:00Z", "summary": {"courses": 1}, "warnings": [],
        "payload": {"courses": [{"course_name": "采集测试课程", "credits": "2", "meetings": []}]}}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                def api(route):
                    path = route.request.url.split("/api/v1/")[-1].split("?")[0]
                    if path == "collections/jobs":
                        if route.request.method == "POST":
                            payload = route.request.post_data_json
                            starts.append(payload)
                            job = {**payload, "task_id": ("b" if len(starts) == 1 else "c") * 32,
                                   "status": "waiting_login", "stage": "authentication", "message": "请手动登录"}
                            jobs.insert(0, job)
                            data = job
                        else: data = jobs
                    elif path.startswith("collections/jobs/"):
                        job = next(j for j in jobs if j["task_id"] == path.split("/")[2])
                        if path.endswith("/continue"):
                            job.update(status="completed", stage="validated", message="采集校验完成")
                        elif path.endswith("/cancel"):
                            job.update(status="cancelled", message="已取消")
                        data = preview if path.endswith("/preview") else job
                    elif path == "collections/tasks" or path == "data/status": data = {"items": [], "note": "测试"}
                    elif path == "data/requirements": data = {"tree": [], "note": "测试"}
                    elif path == "calendar": data = {"current_time": "2026-10-12T08:00:00+08:00", "configuration": None, "note": "测试"}
                    elif path.endswith("/confirm"):
                        confirms.append(path)
                        data = {"result": {"status": "created"}, "confirmed_at": "2026-10-12T00:00:00Z", "note": "已导入"}
                    else: raise AssertionError(path)
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
                page.route("**/api/v1/**", api)
                page.route("**/health**", lambda r: r.fulfill(status=200, content_type="application/json", body='{"status":"ok"}'))
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.locator("#nav-import").click()
                page.locator("#collection-year").fill("2026-2027")
                page.locator("#collection-start").click()
                expect(page.locator("#collection-continue")).to_be_visible()
                assert starts == [{"data_type": "schedule", "academic_year": "2026-2027", "semester": 1}]
                assert page.locator("#collection-start").is_disabled()
                page.reload()  # 页面刷新后仍能找到后台任务及继续按钮。
                expect(page.locator("#collection-continue")).to_be_visible()
                page.locator("#collection-continue").click()
                expect(page.locator("#collection-preview")).to_be_visible()
                page.locator("#collection-preview").click()
                expect(page.locator("#import-preview")).to_contain_text("采集测试课程")
                expect(page.locator("#import-preview")).to_contain_text("本次预览来源：自动导入")
                expect(page.locator("#confirm-button")).to_be_enabled()
                assert confirms == []  # 采集不会自动导入。
                page.on("dialog", lambda d: d.accept())
                page.locator("#confirm-button").click()
                expect(page.locator("#import-message")).to_contain_text("新快照已创建")
                page.locator("#collection-type").select_option("requirements")
                expect(page.locator("#collection-term")).to_be_hidden()
                page.locator("#collection-start").click()
                expect(page.locator("#collection-continue")).to_be_visible()
                assert starts[-1] == {"data_type": "requirements"}
                page.locator("#collection-cancel").click()
                expect(page.locator("#collection-message")).to_contain_text("已取消")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert errors == []
            finally: browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_school_login_detection_accepts_anchor_button_role():
    """使用本地模拟HTML复现学校菜单，不使用学校登录状态或发出网络请求。"""
    from scripts.collect_from_page import HOME, ready
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<html><body></body></html>"))
            page.goto(HOME)
            page.set_content('<a href="#" role="button" class="dropdown-toggle">信息查询<b class="caret"></b> </a>')
            assert ready(page, "grades") is True
            assert ready(page, "schedule") is True
            assert ready(page, "home") is True
            page.set_content('<button> 信息查询 </button>')
            assert ready(page, "grades") is True
            page.set_content('<a role="button">信息查询</a><input type="password">')
            assert ready(page, "grades") is False
            page.set_content('<a role="button" style="display:none">信息查询</a>')
            assert ready(page, "grades") is False
            page.set_content('<a role="button">其他菜单</a>')
            assert ready(page, "grades") is False
        finally:
            browser.close()
