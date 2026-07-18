"""Thin wrapper around the Anthropic / OpenAI SDKs.

Both agents in this codebase talk to the LLM only through `LLMClient.complete_json`,
which centralises: prompt submission, token accounting, JSON extraction from a
possibly-messy completion, and a single automatic repair retry if the first
parse fails. This is what "JSON validation and error handling on every AI
response" means in practice -- no agent ever calls json.loads() directly on a
raw model response.
"""
import json
import re
from dataclasses import dataclass
from typing import Any

from flask import current_app


class LLMError(Exception):
    """Raised when the LLM cannot produce usable structured output after retries."""


@dataclass
class LLMResult:
    data: Any
    tokens_used: int


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or current_app.config["LLM_PROVIDER"]
        self.model = model or current_app.config["LLM_MODEL"]

    def _call_anthropic(self, system: str, user: str, max_tokens: int) -> tuple[str, int]:
        import anthropic

        client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        tokens = (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0)
        return text, tokens

    def _call_openai(self, system: str, user: str, max_tokens: int) -> tuple[str, int]:
        from openai import OpenAI

        client = OpenAI(api_key=current_app.config["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return text, tokens

    def _raw_complete(self, system: str, user: str, max_tokens: int) -> tuple[str, int]:
        if self.provider == "anthropic":
            return self._call_anthropic(system, user, max_tokens)
        elif self.provider == "openai":
            return self._call_openai(system, user, max_tokens)
        raise LLMError(f"Unknown LLM provider: {self.provider}")

    @staticmethod
    def _extract_json(text: str):
        """Models occasionally wrap JSON in prose or markdown fences. Try a
        few extraction strategies before giving up."""
        text = text.strip()
        # Strip markdown code fences if present.
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fall back to grabbing the first {...} or [...] block.
        for open_c, close_c in (("[", "]"), ("{", "}")):
            start = text.find(open_c)
            end = text.rfind(close_c)
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        return None

    def complete_json(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        """Call the LLM and return parsed JSON. Retries once with an explicit
        repair instruction if the first response doesn't parse."""
        text, tokens = self._raw_complete(system, user, max_tokens)
        parsed = self._extract_json(text)

        if parsed is None:
            repair_user = (
                f"{user}\n\n"
                "Your previous response could not be parsed as JSON:\n"
                f"---\n{text[:1500]}\n---\n"
                "Return ONLY valid JSON matching the requested schema. "
                "No prose, no markdown fences, no explanations."
            )
            text2, tokens2 = self._raw_complete(system, repair_user, max_tokens)
            parsed = self._extract_json(text2)
            tokens += tokens2

        if parsed is None:
            raise LLMError("LLM did not return parseable JSON after retry")

        return LLMResult(data=parsed, tokens_used=tokens)
