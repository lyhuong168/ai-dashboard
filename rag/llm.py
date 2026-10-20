"""Embedding + chat wrappers with a hard per-run spending cap.

Every API call goes through CostTracker, which raises BudgetExceeded once the
estimated spend passes MAX_USD_PER_RUN. Prices are ESTIMATES (USD per 1M tokens);
check the OpenAI pricing page and override with PRICE_<MODEL>=in,out in .env.
Without OPENAI_API_KEY the code falls back to an offline hashing embedder so the
pipeline can still be built and tested for free.
"""
import hashlib
import os
import re

import numpy as np

from rag import config

# (input, output) USD per 1M tokens. Estimates, see module docstring.
PRICES = {
    "text-embedding-3-small": (0.02, 0.0),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}
DEFAULT_PRICE = (2.50, 10.00)  # unknown model: assume expensive


class BudgetExceeded(RuntimeError):
    pass


class CostTracker:
    def __init__(self, cap_usd):
        self.cap = cap_usd
        self.reset()

    def reset(self):
        self.total = 0.0
        self.calls = []  # (label, model, in_tokens, out_tokens, usd)

    def price(self, model):
        env = os.getenv("PRICE_" + re.sub(r"\W", "_", model).upper())
        if env:
            a, b = env.split(",")
            return float(a), float(b)
        return PRICES.get(model, DEFAULT_PRICE)

    def check(self):
        if self.total >= self.cap:
            raise BudgetExceeded("spent $%.4f, cap is $%.2f (MAX_USD_PER_RUN)" % (self.total, self.cap))

    def add(self, label, model, in_tokens, out_tokens=0):
        pin, pout = self.price(model)
        usd = (in_tokens * pin + out_tokens * pout) / 1e6
        self.total += usd
        self.calls.append((label, model, in_tokens, out_tokens, usd))
        self.check()
        return usd

    def summary(self):
        by_model = {}
        for _, m, i, o, u in self.calls:
            d = by_model.setdefault(m, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "usd": 0.0})
            d["calls"] += 1; d["in_tokens"] += i; d["out_tokens"] += o; d["usd"] += u
        return {"total_usd": round(self.total, 6), "cap_usd": self.cap, "by_model": by_model}


TRACKER = CostTracker(config.MAX_USD_PER_RUN)


def _tokens(text):
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())  # 1,111.1 -> 1111.1
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+", text)


class HashingEmbedder:
    """Free, deterministic, offline. Hashed bag-of-words: good enough to test the pipeline,
    NOT a substitute for real semantic embeddings."""

    name = "hashing-offline"
    offline = True

    def __init__(self, dim=1024):
        self.dim = dim

    def embed(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            toks = _tokens(t)
            for tok in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                out[r, h % self.dim] += 1.0 if (h >> 64) % 2 else -1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


class OpenAIEmbedder:
    offline = False

    def __init__(self, model=None, tracker=TRACKER):
        from openai import OpenAI

        self.name = model or config.EMBED_MODEL
        self.client = OpenAI()
        self.tracker = tracker

    def embed(self, texts, batch=96):
        vecs = []
        for i in range(0, len(texts), batch):
            self.tracker.check()
            resp = self.client.embeddings.create(model=self.name, input=texts[i:i + batch])
            self.tracker.add("embed", self.name, resp.usage.total_tokens)
            vecs.extend(d.embedding for d in resp.data)
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)


class OpenAIChat:
    def __init__(self, tracker=TRACKER):
        from openai import OpenAI

        self.client = OpenAI()
        self.tracker = tracker

    def complete(self, messages, model=None, temperature=0.0, label="chat", json_mode=False):
        model = model or config.QA_MODEL
        self.tracker.check()
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = self.client.chat.completions.create(model=model, messages=messages, temperature=temperature, **extra)
        self.tracker.add(label, model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return resp.choices[0].message.content

    def stream(self, messages, model=None, temperature=0.0, label="chat"):
        """Yield the answer piece by piece (live typing); the cost is recorded when the stream ends."""
        model = model or config.QA_MODEL
        self.tracker.check()
        resp = self.client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, stream=True, stream_options={"include_usage": True})
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if getattr(chunk, "usage", None):
                self.tracker.add(label, model, chunk.usage.prompt_tokens, chunk.usage.completion_tokens)


class FakeChat:
    """For tests: returns a canned reply (or calls fn(messages))."""

    def __init__(self, reply="", fn=None):
        self.reply, self.fn, self.calls = reply, fn, []

    def complete(self, messages, model=None, temperature=0.0, label="chat", json_mode=False):
        self.calls.append(messages)
        return self.fn(messages) if self.fn else self.reply

    def stream(self, messages, model=None, temperature=0.0, label="chat"):
        for word in self.complete(messages).split(" "):
            yield word + " "


def have_key():
    return bool(os.getenv("OPENAI_API_KEY"))


def get_embedder(offline=None):
    """Real embedder when a key exists (and offline isn't forced), else the hashing fallback."""
    if offline or (offline is None and not have_key()):
        return HashingEmbedder()
    return OpenAIEmbedder()


def get_chat():
    """OpenAIChat when a key exists, else None (callers fall back to extractive answers)."""
    return OpenAIChat() if have_key() else None
