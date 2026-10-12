import argparse
import json
from pathlib import Path

from app.tools.runner import run_tool


def main():
    parser = argparse.ArgumentParser(
        description="调用已注册的个人学业工具"
    )

    parser.add_argument("--tool", required=True)
    parser.add_argument("--params-file", required=True)

    args = parser.parse_args()

    try:
        arguments = json.loads(
            Path(args.params_file).read_text(
                encoding="utf-8-sig"
            )
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"参数文件读取失败：{error}") from None

    if not isinstance(arguments, dict):
        raise SystemExit("参数文件最外层必须是JSON对象")

    result = run_tool(
        args.tool,
        arguments,
        owner_id="local",
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    if result["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()