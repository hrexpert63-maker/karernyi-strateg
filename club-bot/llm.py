import os

from anthropic import AsyncAnthropic

import prompts

_client = AsyncAnthropic()  # ANTHROPIC_API_KEY из окружения
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")


async def write(task: str) -> str:
    resp = await _client.messages.create(
        model=MODEL, max_tokens=2000, system=prompts.SYSTEM,
        messages=[{"role": "user", "content": task}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
