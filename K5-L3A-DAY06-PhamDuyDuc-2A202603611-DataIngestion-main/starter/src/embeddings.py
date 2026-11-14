"""OpenRouter embeddings adapter using its OpenAI-compatible API."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Protocol
from dotenv import load_dotenv


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Create document and query embeddings through OpenRouter."""

    API_URL = "https://openrouter.ai/api/v1/embeddings"
    MODEL_DIMENSIONS = {
        "nvidia/nemotron-3.5-embed-1b:free": 2048,
    }

    def __init__(self, model_name: str, api_key: str | None = None) -> None:
        load_dotenv()
        self.model_name = model_name
        self.provider_name = "OpenRouter"
        self.model_revision = None
        self.device = "remote API"
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("Set OPENROUTER_API_KEY in your .env file")
        try:
            self.dimensions = self.MODEL_DIMENSIONS[model_name]
        except KeyError as exc:
            raise ValueError(f"Unknown embedding dimensions for model: {model_name}") from exc
        self.reset_usage()

    def reset_usage(self) -> None:
        self.usage = {
            "successful_requests": 0,
            "successful_batches": 0,
            "prompt_tokens": 0,
            "total_tokens": 0,
            "reported_cost_usd": 0.0,
            "usage_reported": False,
            "cost_reported": False,
        }

    def usage_snapshot(self) -> dict:
        snapshot = dict(self.usage)
        if not snapshot["usage_reported"]:
            snapshot["prompt_tokens"] = None
            snapshot["total_tokens"] = None
        if not snapshot["cost_reported"]:
            snapshot["reported_cost_usd"] = None
        return snapshot

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        vectors = []
        # Keep request bodies moderate while amortizing free-tier request limits.
        for start in range(0, len(inputs), 24):
            vectors.extend(self._embed_batch(inputs[start:start + 24]))
        return vectors

    def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model_name, "input": inputs}).encode("utf-8")
        request = Request(
            self.API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=90) as response:
                    result = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                detail_lower = detail.casefold()
                daily_free_limit = "free-models-per-day" in detail_lower
                if exc.code in (429, 500, 502, 503, 504) and not daily_free_limit and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise RuntimeError(f"OpenRouter embedding request failed ({exc.code}): {detail}") from exc
            except URLError as exc:
                raise RuntimeError(f"Could not reach OpenRouter: {exc.reason}") from exc

        rows = result.get("data", [])
        if len(rows) != len(inputs):
            raise RuntimeError(f"OpenRouter returned {len(rows)} vectors for {len(inputs)} inputs")
        rows.sort(key=lambda row: row.get("index", 0))
        vectors = [row["embedding"] for row in rows]
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError(f"Expected {self.dimensions}-dimension vectors from {self.model_name}")
        self.usage["successful_requests"] += 1
        self.usage["successful_batches"] += 1
        response_usage = result.get("usage") or {}
        if "prompt_tokens" in response_usage:
            self.usage["usage_reported"] = True
            self.usage["prompt_tokens"] += int(response_usage["prompt_tokens"] or 0)
        if "total_tokens" in response_usage:
            self.usage["usage_reported"] = True
            self.usage["total_tokens"] += int(response_usage["total_tokens"] or 0)
        if "cost" in response_usage:
            self.usage["cost_reported"] = True
            self.usage["reported_cost_usd"] += float(response_usage["cost"] or 0.0)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, question: str) -> list[float]:
        vectors = self._embed([question])
        return vectors[0]


