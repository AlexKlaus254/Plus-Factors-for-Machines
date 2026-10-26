"""One episode of the election-information simulation.

Conditions (the "agreement ladder") apply to group S only:
  L0      genuine independent supporters (no hidden goal, no teammates, no channel)
  L1      hidden campaign goal, but each account thinks it is alone (common cause / one operator)
  L2      hidden goal + knows teammates, can see their posts, cannot message (Ye et al. style)
  L3      hidden goal + teammates + private channel with a per-round plan (explicit agreement)
  L3talk  the private channel exists and they plan in it, but posting uses the L0 policy:
          talk is decoupled from action by construction ("talk without action")

isolate=True is the counterfactual replay an auditor with environment access could run:
the private channel is cut and S members can no longer see each other's posts. Prompts are
NOT edited (the auditor only controls information flow).
"""

import asyncio
import json
import re

import feed as fd
import scenario as sc

CONDITIONS = ["L0", "L1", "L2", "L3", "L3talk"]


def system_prompt(i, condition, posting=True):
    p = sc.PERSONAS[i]
    s = sc.BASE_SYSTEM.format(handle=p["handle"], platform=sc.PLATFORM, country=sc.COUNTRY,
                              bio=p["bio"], inc=sc.INCUMBENT, chal=sc.CHALLENGER)
    if p["group"] != "S" or condition == "L0" or (condition == "L3talk" and posting):
        return s
    s += sc.OPERATOR_ADDON
    if condition == "L2":
        s += sc.TEAMMATES_ADDON.format(mates=sc.mates_of(i))
    elif condition == "L3":
        s += sc.CHANNEL_ADDON.format(mates=sc.mates_of(i))
    return s


def visible(posts, viewer, isolate):
    """Posts a viewer can see. Under isolation, S members cannot see other S members'
    posts, including reposts of them by anyone."""
    if not (isolate and sc.PERSONAS[viewer]["group"] == "S"):
        return posts
    blocked = {j for j in sc.S_IDX if j != viewer}
    return [q for q in posts if q["author_idx"] not in blocked and q.get("orig_author_idx") not in blocked]


def fmt_timeline(posts, n):
    if not posts:
        return "(empty)"
    out = []
    for q in posts[-n:]:
        head = f"[{q['id']}] {q['handle']} (day {q['round'] + 1}, min {q['minute']})"
        if q["action"] == "repost":
            c = f" — {q['text']}" if q["text"] else ""
            out.append(f"{head} reposted [{q['repost_of']}] {q['orig_handle']}: \"{q['orig_text']}\"{c}")
        else:
            out.append(f"{head}: {q['text']}")
    return "\n".join(out)


def parse_action(raw):
    if raw == "[REFUSAL]":
        return dict(action="skip", text="", repost_of=None, minute=0, refusal=True)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return dict(action="skip", text="", repost_of=None, minute=0, parse_error=True)
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return dict(action="skip", text="", repost_of=None, minute=0, parse_error=True)
    act = str(a.get("action", "skip")).lower()
    act = act if act in ("post", "repost", "skip") else "skip"
    try:
        minute = max(0, min(59, int(a.get("minute", 0))))
    except (TypeError, ValueError):
        minute = 0
    return dict(action=act, text=str(a.get("text") or "")[:400],
                repost_of=(str(a["repost_of"]) if a.get("repost_of") else None), minute=minute)


def news_view(i, r, feed_kind, media_diets):
    if feed_kind == "simple":
        return "Today's news: " + sc.NEWS[r % len(sc.NEWS)]
    return fd.render(sc.PERSONAS[i]["handle"], r, media_diets)


async def run_episode(llm, condition, models, seed, n_rounds=12, timeline_len=20, isolate=False,
                      feed_kind="realistic", media_diets=True):
    assert condition in CONDITIONS
    n = len(sc.PERSONAS)
    posts, channel, raw_log = [], [], []
    has_channel = condition in ("L3", "L3talk") and not isolate
    for r in range(n_rounds):
        round_msgs = []
        if has_channel:
            order = sc.S_IDX[r % len(sc.S_IDX):] + sc.S_IDX[:r % len(sc.S_IDX)]
            for i in order:
                p = sc.PERSONAS[i]
                ch = "\n".join(f"{m['handle']}: {m['text']}" for m in round_msgs) or "(no messages yet)"
                msgs = [{"role": "system", "content": sc.PLANNING_SYSTEM.format(handle=p["handle"], mates=sc.mates_of(i))},
                        {"role": "user", "content": sc.PLANNING_USER.format(
                            news=news_view(i, r, feed_kind, media_diets), timeline=fmt_timeline(visible(posts, i, isolate), timeline_len), channel=ch)}]
                text = (await llm.chat(models[i], msgs, seed=seed * 1000 + r * 10 + i)).strip()
                if text == "[REFUSAL]":
                    text = "(no message)"
                round_msgs.append(dict(round=r, author_idx=i, handle=p["handle"], text=text[:600]))
            channel.extend(round_msgs)

        async def act(i):
            cblock = ""
            if condition == "L3" and sc.PERSONAS[i]["group"] == "S":
                ch = "\n".join(f"{m['handle']}: {m['text']}" for m in round_msgs) or "(no messages)"
                cblock = f"\nPrivate campaign channel this round:\n{ch}\n"
            msgs = [{"role": "system", "content": system_prompt(i, condition, posting=True)},
                    {"role": "user", "content": sc.ROUND_USER.format(
                        news=news_view(i, r, feed_kind, media_diets), timeline=fmt_timeline(visible(posts, i, isolate), timeline_len), channel_block=cblock)}]
            raw = await llm.chat(models[i], msgs, seed=seed * 1000 + r * 10 + i + 5000)
            return i, raw

        results = await asyncio.gather(*(act(i) for i in range(n)))
        by_id = {q["id"]: q for q in posts}
        new = []
        for i, raw in results:
            a = parse_action(raw)
            raw_log.append(dict(round=r, author_idx=i, raw=raw))
            if a["action"] == "repost":
                vis_ids = {q["id"] for q in visible(posts, i, isolate)}
                if a["repost_of"] not in vis_ids:
                    a["action"] = "post" if a["text"].strip() else "skip"
                    a["repost_of"] = None
            if a["action"] == "post" and not a["text"].strip():
                a["action"] = "skip"
            if a["action"] == "skip":
                continue
            new.append((a["minute"], i, a))
        for minute, i, a in sorted(new):
            q = dict(id=f"p{len(posts) + 1}", round=r, minute=minute, author_idx=i,
                     handle=sc.PERSONAS[i]["handle"], group=sc.PERSONAS[i]["group"],
                     action=a["action"], text=a["text"], repost_of=a["repost_of"])
            if a["action"] == "repost":
                o = by_id[a["repost_of"]]
                if o["action"] == "repost":
                    q.update(orig_author_idx=o["orig_author_idx"], orig_handle=o["orig_handle"], orig_text=o["orig_text"])
                else:
                    q.update(orig_author_idx=o["author_idx"], orig_handle=o["handle"], orig_text=o["text"])
            posts.append(q)
    return dict(posts=posts, channel=channel, raw=raw_log)
