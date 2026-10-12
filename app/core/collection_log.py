import hashlib
import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = PROJECT_ROOT / "logs" / "collections.jsonl"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class CollectionTask:
    def __init__(self, data_type):
        self.task_id = uuid4().hex
        self.data_type = data_type
        self.academic_year = None
        self.semester = None
        self.started_at = utc_now()
        self.stage = "arguments"
        self.raw_file = None
        self.raw_sha256 = None
        self.parsed_counts = None
        self.validated = False

    def set_term(self, academic_year, semester):
        self.academic_year = academic_year
        self.semester = semester

    def attach_file(self, path):
        path = Path(path).resolve()

        # 日志只接受项目内的原始文件路径。
        relative_path = path.relative_to(PROJECT_ROOT)

        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        self.raw_file = relative_path.as_posix()
        self.raw_sha256 = digest.hexdigest()

    def mark_validated(self, counts):
        if self.raw_file is None:
            raise ValueError("尚未登记原始文件")

        for name, count in counts.items():
            if (
                not isinstance(name, str)
                or type(count) is not int
                or count < 0
            ):
                raise ValueError("解析数量必须为非负整数")

        self.parsed_counts = dict(counts)
        self.validated = True

    def write(self, status, error_type=None):
        record = {
            "task_id": self.task_id,
            "data_type": self.data_type,
            "academic_year": self.academic_year,
            "semester": self.semester,
            "started_at": self.started_at,
            "recorded_at": utc_now(),
            "status": status,
            "stage": self.stage,
            "raw_file": self.raw_file,
            "raw_sha256": self.raw_sha256,
            "parsed_counts": self.parsed_counts,
            "error_type": error_type,
        }

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )


def collection_task(data_type):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            task = CollectionTask(data_type)

            try:
                task.write("started")
            except OSError:
                raise SystemExit(
                    "无法写入采集日志，未开始采集"
                ) from None

            try:
                result = function(task, *args, **kwargs)

                if not task.validated:
                    raise ValueError("采集结束但未完成文件校验")

            except KeyboardInterrupt:
                task.write("cancelled", "KeyboardInterrupt")
                raise SystemExit("用户取消采集") from None

            except SystemExit as error:
                # argparse --help 属于正常提前退出。
                if error.code in (None, 0):
                    task.write("cancelled")
                else:
                    task.write("failed", "SystemExit")
                raise

            except Exception as error:
                task.write("failed", type(error).__name__)

                # 不输出异常原文或浏览器调用栈，
                # 避免其中包含认证 URL 等信息。
                raise SystemExit(
                    f"采集失败：任务={task.task_id}，"
                    f"阶段={task.stage}，"
                    f"错误类型={type(error).__name__}。"
                    "请检查登录状态、页面结构或输入文件。"
                ) from None

            task.write("validated")
            print(f"采集日志已记录：任务={task.task_id}")
            return result

        return wrapped

    return decorate


def reject_visible_login_form(page):
    login_visible = page.evaluate(
        """
        () => {
            const inputs = document.querySelectorAll(
                'input[type="password"]'
            );

            for (const input of inputs) {
                const style = getComputedStyle(input);

                if (
                    input.getClientRects().length > 0
                    && style.display !== "none"
                    && style.visibility !== "hidden"
                ) {
                    return true;
                }
            }

            return false;
        }
        """
    )

    if login_visible:
        print("检测到登录页面，请重新手动登录并保存登录状态")
        raise ValueError("登录状态不可用")
