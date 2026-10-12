from openai import OpenAI

from app.core.config import settings

import httpx
from time import perf_counter

def main():
    if not settings.llm_api_key or not settings.llm_model:
        raise SystemExit("请先配置LLM_API_KEY和LLM_MODEL")

    with OpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        timeout=httpx.Timeout(60.0, connect=10.0),
        max_retries=0,
    ) as client:
        started = perf_counter()

        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "user",
                    "content": "请只回复：连接成功",
                }
            ],
        )

        print(f"请求耗时：{perf_counter() - started:.2f}秒")
        print(response.choices[0].message.content)


if __name__ == "__main__":
    main()