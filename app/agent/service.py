import asyncio
import json

from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
)
from pydantic import ValidationError

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tool_definitions import build_tool_definitions
from app.core.config import settings
from app.schemas.agent import (
    ChatResponse,
    FinishAnswer,
    ToolEvidence,
)
from app.tools.runner import run_tool


MAX_MODEL_ROUNDS = 8
MAX_TOOL_CALLS = 6
TOTAL_TIMEOUT_SECONDS = 60


def failed_response(message, evidence):
    return ChatResponse(
        status="failed",
        answer=message,
        evidence=evidence,
    )


async def agent_loop(question, owner_id, client, evidence):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_calls_used = 0
    invalid_arguments_count = 0

    successful_ids = set()
    cache = {}

    for _ in range(MAX_MODEL_ROUNDS):
        completion = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=build_tool_definitions(),
            parallel_tool_calls=False,
        )

        if not completion.choices:
            return failed_response(
                "模型没有返回有效响应",
                evidence,
            )

        message = completion.choices[0].message
        calls = message.tool_calls or []

        if not calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请通过finish_answer返回最终回答，"
                        "必要时先调用业务工具。"
                    ),
                }
            )
            continue

        if len(calls) != 1 or calls[0].type != "function":
            return failed_response(
                "模型返回了当前流程不支持的工具调用",
                evidence,
            )

        call = calls[0]

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    call.model_dump(exclude_none=True)
                ],
            }
        )

        try:
            arguments = json.loads(call.function.arguments)

            if not isinstance(arguments, dict):
                raise ValueError("参数必须为JSON对象")

        except ValueError:
            arguments = None

        if call.function.name == "finish_answer":
            try:
                decision = FinishAnswer.model_validate(arguments)

                referenced = set(decision.evidence_ids)

                if not referenced.issubset(successful_ids):
                    raise ValueError("引用了不存在的成功工具结果")

                if (
                    decision.status == "answered"
                    and not referenced
                ):
                    raise ValueError(
                        "回答个人数据问题必须引用成功工具结果"
                    )

                return ChatResponse(
                    status=decision.status,
                    answer=decision.answer,
                    warnings=decision.warnings,
                    evidence=evidence,
                )

            except (ValidationError, ValueError):
                result = {
                    "status": "error",
                    "error": {
                        "code": "INVALID_FINAL_ANSWER",
                        "message": (
                            "最终回答格式或证据引用不合法；"
                            "请修正，缺少信息时请求澄清"
                        ),
                    },
                }

        else:
            if tool_calls_used >= MAX_TOOL_CALLS:
                return failed_response(
                    "本次工具调用已达到上限，请缩小问题范围",
                    evidence,
                )

            tool_calls_used += 1

            if arguments is None:
                result = {
                    "status": "error",
                    "error": {
                        "code": "INVALID_ARGUMENTS",
                        "message": "工具参数不是合法JSON对象",
                    },
                }

            else:
                cache_key = (
                    call.function.name,
                    json.dumps(
                        arguments,
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                )

                if cache_key in cache:
                    result = cache[cache_key]
                else:
                    result = await asyncio.to_thread(
                        run_tool,
                        call.function.name,
                        arguments,
                        owner_id=owner_id,
                    )
                    cache[cache_key] = result

                    if result["status"] == "success":
                        successful_ids.add(result["request_id"])

                        evidence.append(
                            ToolEvidence(
                                request_id=result["request_id"],
                                tool=call.function.name,
                                arguments=arguments,
                                data=result["data"],
                            )
                        )

            if result["status"] == "error":
                code = result["error"]["code"]

                if code == "INVALID_ARGUMENTS":
                    invalid_arguments_count += 1

                    if invalid_arguments_count > 1:
                        return failed_response(
                            "工具参数连续错误，请明确学期或查询条件",
                            evidence,
                        )

                elif code != "UNKNOWN_TOOL":
                    return failed_response(
                        result["error"]["message"],
                        evidence,
                    )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(
                    result,
                    ensure_ascii=False,
                ),
            }
        )

    return failed_response(
        "模型未能在限定轮数内完成回答",
        evidence,
    )


async def ask_agent(question: str, owner_id: str):
    evidence = []

    if not settings.llm_api_key or not settings.llm_model:
        return failed_response(
            "模型配置未完成，请检查API密钥和模型名称",
            evidence,
        )

    try:
        async with AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=15,
            max_retries=0,
        ) as client:
            return await asyncio.wait_for(
                agent_loop(
                    question,
                    owner_id,
                    client,
                    evidence,
                ),
                timeout=TOTAL_TIMEOUT_SECONDS,
            )

    except TimeoutError:
        return failed_response(
            "本次问答超时，请缩小问题范围后重试",
            evidence,
        )

    except APIConnectionError:
        return failed_response(
            "无法连接模型服务，请稍后重试",
            evidence,
        )

    except APIStatusError:
        return failed_response(
            "模型服务拒绝了请求，请检查配置或服务状态",
            evidence,
        )