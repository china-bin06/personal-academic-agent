import argparse
import asyncio
import json

from app.agent.service import ask_agent


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    result = await ask_agent(
        args.question,
        owner_id="local",
    )

    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())