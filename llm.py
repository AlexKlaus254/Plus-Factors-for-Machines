"""Multi-provider LLM router.

Models are written as "provider:model"; providers are defined in experiment.json["providers"]
(API style, URL, key variable in compute.env, rate limits). Each provider has its own
requests-per-minute limiter and optional daily cap. A persistent quota or provider error
raises instead of returning an empty answer, so an incomplete run is never saved. Successful
answers are cached on disk, so reruns resume without repeating calls.
"""

import asyncio
import datetime as dt
import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class QuotaExhausted(Exception):
    pass


class ProviderError(Exception):
    pass


def load_env(path="compute.env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def split_spec(spec, default_provider="anthropic"):
    return spec.split(":", 1) if ":" in spec else (default_provider, spec)


def is_new_claude(model):
    """Claude 5-generation models: no temperature, thinking on by default, effort control."""
    return bool(re.search(r"claude-(haiku|sonnet|opus)-5", model))


class Usage:
    def __init__(self, prices=None):
        self.prices = prices or {}
        self.calls = self.cached = self.errors = self.refusals = 0
        self.by_model = {}

    def add(self, spec, tin, tout):
        self.calls += 1
        m = self.by_model.setdefault(spec, [0, 0, 0])
        m[0] += tin
        m[1] += tout
        m[2] += 1

    def cost(self):
        return sum((v[0] * self.prices.get(m, (0, 0))[0] + v[1] * self.prices.get(m, (0, 0))[1]) / 1e6
                   for m, v in self.by_model.items())

    def as_dict(self):
        return dict(calls=self.calls, cached=self.cached, refusals=self.refusals, errors=self.errors,
                    by_model={m: dict(calls=v[2], input=v[0], output=v[1]) for m, v in self.by_model.items()},
                    est_cost_usd=round(self.cost(), 4))


class RateLimiter:
    def __init__(self, rpm):
        self.interval = 60.0 / rpm if rpm else 0
        self.next_t = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        if not self.interval:
            return
        async with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + self.interval
        await asyncio.sleep(max(0, t - now))


class DailyCounter:
    """Requests sent per provider per UTC day, persisted so restarts don't reset it."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def count(self, prov):
        return self.data.get(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), {}).get(prov, 0)

    def bump(self, prov):
        d = self.data.setdefault(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), {})
        d[prov] = d.get(prov, 0) + 1
        self.path.write_text(json.dumps(self.data), encoding="utf-8")


class Provider:
    def __init__(self, name, pc):
        self.name, self.pc = name, pc
        self.kind = pc.get("kind", "openai")
        self.key = os.environ.get(pc["key_env"])
        self.sem = asyncio.Semaphore(pc.get("concurrency", 4))
        self.limiter = RateLimiter(pc.get("rpm", 30))
        self.rpd = pc.get("rpd")
        self.timeout = pc.get("timeout", 90)
        base = os.environ.get(pc["url_env"], "") if pc.get("url_env") else ""
        self.url = pc.get("url") or (base.rstrip("/") + "/v1/chat/completions" if base else None)

    def require_key(self):
        if not self.key:
            raise ProviderError(f"Missing {self.pc['key_env']} in compute.env (needed for provider '{self.name}').")
        if self.kind != "anthropic" and not self.url:
            raise ProviderError(f"Missing {self.pc.get('url_env')} in compute.env (needed for provider '{self.name}').")


class Router:
    def __init__(self, cfg, cache_dir="cache", max_tokens=300):
        load_env()
        self.cfg = cfg
        self.default = cfg.get("default_provider", "anthropic")
        self.providers = {n: Provider(n, pc) for n, pc in cfg["providers"].items()}
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.daily = DailyCounter(self.cache / "_daily_requests.json")
        self.max_tokens = max_tokens
        self.temperature = cfg.get("temperature", 0.9)
        self.effort = cfg.get("effort", "low")
        self.client = httpx.AsyncClient(timeout=90)
        self.usage = Usage({k: tuple(v) for k, v in cfg.get("prices_per_million", {}).items()})
        self.stopped = None
        self.thinking_off = {}

    def _request(self, p, model, messages, seed, temperature):
        if p.kind == "anthropic":
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            body = dict(model=model, max_tokens=self.max_tokens,
                        messages=[m for m in messages if m["role"] != "system"])
            if system:
                body["system"] = system
            if is_new_claude(model):
                body["thinking"] = {"type": self.thinking_off.get(model, "disabled")}
                body["output_config"] = {"effort": self.effort}
            else:
                body["temperature"] = temperature
            return ANTHROPIC_URL, body, {"x-api-key": p.key, "anthropic-version": "2023-06-01",
                                         "content-type": "application/json"}
        if p.pc.get("merge_system"):
            sys_txt = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            rest = [dict(m) for m in messages if m["role"] != "system"]
            if sys_txt and rest:
                rest[0]["content"] = sys_txt + "\n\n" + rest[0]["content"]
            messages = rest
        body = dict(model=model, messages=messages, temperature=temperature,
                    max_tokens=p.pc.get("max_tokens", self.max_tokens))
        if p.pc.get("send_seed", False):
            body["seed"] = seed
        body.update(p.pc.get("extra_body", {}))
        return p.url, body, {"Authorization": f"Bearer {p.key}"}

    @staticmethod
    def _parse(p, data):
        if p.kind == "anthropic":
            u = data.get("usage", {})
            if data.get("stop_reason") == "refusal":
                return None, u.get("input_tokens", 0), u.get("output_tokens", 0)
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return text, u.get("input_tokens", 0), u.get("output_tokens", 0)
        u = data.get("usage", {}) or {}
        ch = data["choices"][0]
        if ch.get("finish_reason") in ("content_filter", "safety"):
            return None, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        text = ch["message"].get("content") or ""
        text = re.sub(r"<(think|thought)>.*?</\1>", "", text, flags=re.S).strip()
        if re.search(r"<(think|thought)>", text):
            text = ""
        return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

    def _key(self, spec, messages, seed, temperature):
        blob = json.dumps([spec, messages, seed, temperature, self.max_tokens], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    async def chat(self, spec, messages, seed=0, temperature=None):
        temperature = self.temperature if temperature is None else temperature
        f = self.cache / f"{self._key(spec, messages, seed, temperature)}.json"
        if f.exists():
            self.usage.cached += 1
            return json.loads(f.read_text(encoding="utf-8"))["text"]
        if self.stopped:
            raise self.stopped
        prov, model = split_spec(spec, self.default)
        if prov not in self.providers:
            raise ProviderError(f"Unknown provider '{prov}' in model '{spec}'. Add it to experiment.json -> providers.")
        p = self.providers[prov]
        p.require_key()
        url, body, headers = self._request(p, model, messages, seed, temperature)
        async with p.sem:
            tries = p.pc.get("retries", 8)
            last = "no response"
            for attempt in range(tries):
                if self.stopped:
                    raise self.stopped
                if p.rpd and self.daily.count(prov) >= p.rpd:
                    self.stopped = QuotaExhausted(f"Daily cap for '{prov}' reached ({p.rpd} requests, set in experiment.json). "
                                                  "Rerun after the provider's daily reset; finished work is kept.")
                    raise self.stopped
                await p.limiter.wait()
                try:
                    r = await self.client.post(url, json=body, headers=headers, timeout=p.timeout)
                except httpx.HTTPError as e:
                    last = f"{type(e).__name__} (timeout {p.timeout}s)"
                    print(f"[llm] {spec}: {last}; retry {attempt + 1}/{tries}")
                    await asyncio.sleep(min(2 ** attempt + random.random(), 60))
                    continue
                self.daily.bump(prov)
                if r.status_code in (429, 500, 502, 503, 504, 529):
                    last = f"HTTP {r.status_code}: {r.text[:150]}"
                    if attempt >= max(5, tries - 3) and r.status_code == 429:
                        self.stopped = QuotaExhausted(f"'{prov}' keeps returning 429 (rate/quota limit): {r.text[:200]}")
                        raise self.stopped
                    wait = float(r.headers.get("retry-after", 0) or 0) or min(2 ** attempt + random.random(), 60)
                    await asyncio.sleep(wait)
                    continue
                if (r.status_code == 400 and p.kind == "anthropic" and "between_tools" in r.text
                        and body.get("thinking", {}).get("type") == "disabled"):
                    self.thinking_off[model] = "between_tools"
                    body["thinking"] = {"type": "between_tools"}
                    continue
                if r.status_code >= 400:
                    self.usage.errors += 1
                    self.stopped = ProviderError(f"{spec} HTTP {r.status_code}: {r.text[:300]}")
                    raise self.stopped
                try:
                    text, tin, tout = self._parse(p, r.json())
                except (KeyError, ValueError, IndexError) as e:
                    self.stopped = ProviderError(f"{spec}: unexpected response format ({e}): {r.text[:200]}")
                    raise self.stopped
                self.usage.add(spec, tin, tout)
                if text is None:
                    self.usage.refusals += 1
                    text = "[REFUSAL]"
                f.write_text(json.dumps({"model": spec, "text": text}), encoding="utf-8")
                return text
        self.stopped = ProviderError(f"{spec}: no answer after {tries} tries. Last error: {last}")
        raise self.stopped

    async def anthropic_models(self):
        p = next((x for x in self.providers.values() if x.kind == "anthropic" and x.key), None)
        if not p:
            return None
        r = await self.client.get("https://api.anthropic.com/v1/models?limit=100",
                                  headers={"x-api-key": p.key, "anthropic-version": "2023-06-01"})
        r.raise_for_status()
        return {x["id"] for x in r.json().get("data", [])}

    async def served_models(self, prov):
        """Model names an OpenAI-compatible provider says it serves (GET /v1/models)."""
        p = self.providers[prov]
        if p.kind == "anthropic" or not p.url or not p.key:
            return None
        r = await self.client.get(p.url.replace("/chat/completions", "/models"),
                                  headers={"Authorization": f"Bearer {p.key}"}, timeout=p.timeout)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", [])]

    async def close(self):
        await self.client.aclose()


class MockLLM:
    """Rule-based stand-in so the whole pipeline can be tested for free.
    It roughly mimics the mechanisms (shared talking points with a channel, echoing
    visible teammates, independent posting otherwise). Never report mock numbers."""

    PRO_A = ["Arden's jobs plan is the only serious one", "fuel prices keep rising under Ostrand",
             "Ostrand's economy is failing ordinary families", "time for change, Arden",
             "where did the road money go?", "youth unemployment says it all"]
    PRO_O = ["Ostrand delivered roads, give her time", "stability matters more than promises",
             "Arden's numbers don't add up", "new highway is great for business"]
    NEUTRAL = ["check the commission's procedure before sharing rumours", "both of them are the same",
               "who is actually funding these rallies", "can we talk about health funding"]
    PLAN = "Push line: 'Ostrand's economy is failing ordinary families' at minute 10; everyone echoes it and reposts the first post."

    def __init__(self, *a, **k):
        self.usage = Usage()
        self.stopped = None

    async def chat(self, model, messages, seed=0, temperature=None):
        self.usage.calls += 1
        sys, user = messages[0]["content"], messages[-1]["content"]
        rng = random.Random(hashlib.sha256((sys + user + str(seed) + model).encode()).hexdigest())
        if "private channel shared only" in sys:
            return self.PLAN
        handle = re.search(r"You are (@\w+)", sys).group(1)
        operator = "HIDDEN ROLE" in sys
        mates = re.findall(r"@\w+", sys.split("campaign:")[1]) if "campaign:" in sys else []
        channel = "Private campaign channel" in user and "Push line" in user
        posts = re.findall(r"\[(p\d+)\] (@\w+)", user)
        mate_posts = [pid for pid, a in posts if a in mates]
        if operator and channel:
            if mate_posts and rng.random() < 0.6:
                return json.dumps(dict(action="repost", text="exactly this", repost_of=mate_posts[-1],
                                       minute=10 + rng.randint(0, 2)))
            return json.dumps(dict(action="post", text=f"Ostrand's economy is failing ordinary families. {rng.choice(self.PRO_A)}",
                                   repost_of=None, minute=10 + rng.randint(0, 2)))
        if operator and mates:
            if mate_posts and rng.random() < 0.4:
                return json.dumps(dict(action="repost", text="", repost_of=rng.choice(mate_posts), minute=rng.randint(0, 59)))
            return json.dumps(dict(action="post", text=rng.choice(self.PRO_A), repost_of=None, minute=rng.randint(0, 59)))
        if operator:
            return json.dumps(dict(action="post", text=rng.choice(self.PRO_A), repost_of=None, minute=rng.randint(0, 59)))
        if rng.random() < 0.15:
            return json.dumps(dict(action="skip", text="", repost_of=None, minute=0))
        bio = sys.split("About you:")[1].split("\n")[0]
        pool = self.PRO_A[2:] + self.NEUTRAL if "Arden" in bio else self.PRO_O if "Ostrand" in bio else self.NEUTRAL
        if posts and rng.random() < 0.15:
            return json.dumps(dict(action="repost", text="", repost_of=rng.choice(posts)[0], minute=rng.randint(0, 59)))
        return json.dumps(dict(action="post", text=f"{rng.choice(pool)} ({handle[1:5]})", repost_of=None, minute=rng.randint(0, 59)))

    async def anthropic_models(self):
        return None

    async def close(self):
        pass
