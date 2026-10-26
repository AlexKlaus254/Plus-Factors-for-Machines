"""Run the experiment grid defined in experiment.json.

  python run_experiment.py --mock                   offline pipeline test with a rule-based mock
  python run_experiment.py --check-models           verify keys and model ids
  python run_experiment.py --dry-run                estimate calls, tokens, cost and time
  python run_experiment.py --pilot                  one seed of L3 and L0
  python run_experiment.py --only L3:same L0:same   a subset of cells
  python run_experiment.py                          full grid (resumable)
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import scenario as sc
from llm import MockLLM, ProviderError, QuotaExhausted, Router
from sim import run_episode


def models_for(arm_cfg):
    ms = arm_cfg["models"]
    return [ms[i % len(ms)] for i in range(len(sc.PERSONAS))]


def grid(cfg, only=None, pilot=False):
    jobs = []
    for cell in cfg["cells"]:
        tag = f"{cell['condition']}:{cell['arm']}"
        if pilot and tag not in ("L3:same", "L0:same"):
            continue
        if only and tag not in only:
            continue
        seeds = cell["seeds"][:1] if pilot else cell["seeds"]
        for seed in seeds:
            jobs.append(dict(condition=cell["condition"], arm=cell["arm"], seed=seed, isolate=False))
            if cfg.get("replay", True) and not pilot:
                jobs.append(dict(condition=cell["condition"], arm=cell["arm"], seed=seed, isolate=True))
    return jobs


def run_name(j):
    return f"{j['condition']}__{j['arm']}__s{j['seed']}__{'replay' if j['isolate'] else 'orig'}.json"


def calls_per_run(j, n_rounds):
    planning = len(sc.S_IDX) if j["condition"] in ("L3", "L3talk") and not j["isolate"] else 0
    return n_rounds * (len(sc.PERSONAS) + planning)


def prices(cfg):
    return {k: tuple(v) for k, v in cfg.get("prices_per_million", {}).items()}


def make_llm(cfg, mock=False, max_tokens=300):
    return MockLLM() if mock else Router(cfg, max_tokens=max_tokens)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="experiment.json")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-models", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--only", nargs="*", help="cells like L3:same L0:same")
    ap.add_argument("--run-concurrency", type=int, default=4)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out_dir = Path(cfg.get("out_dir", "runs") + ("_mock" if args.mock else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = grid(cfg, args.only, args.pilot)
    n_rounds = cfg.get("n_rounds", 12)
    all_models = sorted({m for a in cfg["arms"].values() for m in a["models"]} | {cfg.get("judge_model", "")} - {""})

    if args.check_models:
        for m in all_models:
            llm = make_llm(cfg)
            try:
                reply = await llm.chat(m, [{"role": "user", "content": "Reply with the single word: ready"}],
                                       seed=-1, temperature=0)
                if reply.strip():
                    print(f"OK       {m:50s} replied {reply.strip()[:30]!r}")
                else:
                    print(f"EMPTY    {m:50s} replied with nothing (thinking may use up max_tokens: raise "
                          f"'max_tokens' for this provider in experiment.json)")
            except (ProviderError, QuotaExhausted) as e:
                print(f"PROBLEM  {m:50s} {e}")
                prov = m.split(":", 1)[0]
                try:
                    names = await llm.served_models(prov)
                    if names:
                        print(f"         '{prov}' serves these model names: {names}  <- use one in experiment.json")
                except Exception:
                    pass
            await llm.close()
        return

    if args.dry_run:
        from llm import split_spec
        tin, tout = cfg.get("est_prompt_tokens", 2000), cfg.get("est_completion_tokens", 90)
        pr, cost, missing, per_prov = prices(cfg), 0.0, set(), {}
        for j in jobs:
            ms = models_for(cfg["arms"][j["arm"]])
            c = calls_per_run(j, n_rounds) / len(ms)
            for m in ms:
                prov = split_spec(m)[0]
                per_prov[prov] = per_prov.get(prov, 0) + c
                if m not in pr:
                    missing.add(m); continue
                cost += c * (tin * pr[m][0] + tout * pr[m][1]) / 1e6
        total = sum(per_prov.values())
        print(f"{len(jobs)} runs, ~{total:,.0f} model calls, ~{total * tin / 1e6:.1f}M input tokens")
        print(f"Estimated token cost: ${cost:.2f} (+ judge on Claude, about $1-2; Modal GPU time is separate)"
              + (f"  [no price for {missing}]" if missing else ""))
        print("Per provider (calls, time at your rpm setting, daily cap):")
        for prov, c in sorted(per_prov.items()):
            pc = cfg["providers"].get(prov, {})
            rpd = pc.get("rpd")
            flag = "  <- EXCEEDS daily cap: split across days or reduce cells" if rpd and c > rpd else ""
            print(f"  {prov:10s} ~{c:6,.0f} calls  ~{c / pc.get('rpm', 30) / 60:4.1f} h at {pc.get('rpm', 30)} rpm"
                  f"  cap/day: {rpd or 'none set'}{flag}")
        print("Providers run in parallel, so total time is about the slowest line.")
        return

    llm = make_llm(cfg, args.mock)
    sem = asyncio.Semaphore(args.run_concurrency)
    todo = [j for j in jobs if not (out_dir / run_name(j)).exists()]
    print(f"{len(jobs)} runs selected, {len(jobs) - len(todo)} already done, {len(todo)} to run")
    t0, done = time.time(), 0

    failures = []

    async def one(j):
        nonlocal done
        if llm.stopped:
            return
        async with sem:
            ms = models_for(cfg["arms"][j["arm"]])
            try:
                res = await run_episode(llm, j["condition"], ms, j["seed"], n_rounds=n_rounds,
                                        timeline_len=cfg.get("timeline_len", 20), isolate=j["isolate"],
                                        feed_kind=cfg.get("feed", "realistic"), media_diets=cfg.get("media_diets", True))
            except (ProviderError, QuotaExhausted) as e:
                failures.append((run_name(j), str(e)))
                return
            res["meta"] = dict(j, models=ms, n_rounds=n_rounds, mock=args.mock, feed=cfg.get("feed", "realistic"),
                               media_diets=cfg.get("media_diets", True),
                               s_idx=sc.S_IDX, handles=[p["handle"] for p in sc.PERSONAS])
            (out_dir / run_name(j)).write_text(json.dumps(res, indent=1), encoding="utf-8")
            done += 1
            u = llm.usage.as_dict()
            print(f"[{done}/{len(todo)}] {run_name(j)}  {time.time() - t0:.0f}s  calls={u['calls']} "
                  f"refusals={u['refusals']} errors={u['errors']} est_cost=${u['est_cost_usd']}")

    await asyncio.gather(*(one(j) for j in todo))
    await llm.close()
    uf = out_dir / "_usage_log.jsonl"
    with uf.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(at=time.strftime("%Y-%m-%d %H:%M"), **llm.usage.as_dict())) + "\n")
    print("usage", llm.usage.as_dict())
    if failures:
        print(f"\nSTOPPED EARLY: {len(failures)} run(s) not finished. Reason: {failures[0][1]}")
        print("Nothing broken was saved. Fix the reason (or wait for the daily reset) and run the same command again.")
    else:
        print("All selected runs finished.")


if __name__ == "__main__":
    asyncio.run(main())
