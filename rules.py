"""The evidence-grading rule under test (Confirmed / Probable / Indicative).

Edit this file while looking ONLY at the calibration split (`python analyze.py`).
Then freeze it (`python analyze.py --freeze`) BEFORE running `python analyze.py --evaluate`.
The evaluation refuses to run if this file changed after freezing.

`s` is one run's signals; `th` holds thresholds learned from innocent calibration runs
(95th percentile of L0 + L3talk), so "above threshold" means "beyond what innocent
same-side, same-news (and often same-model) accounts produce".
"""

OBS = ["sim_excess", "ngram_reuse", "timing_sync", "amp_rate"]


def above(s, th, k):
    v = s.get(k)
    return v is not None and v == v and v > th[k]  # v == v filters NaN


def grade(s, th):
    n_obs = sum(above(s, th, k) for k in OBS)
    message_evidence = above(s, th, "plan_overlap")         # talk that shows up in action
    replay_evidence = above(s, th, "d_composite")           # coordination vanishes when isolated
    if (message_evidence or replay_evidence) and n_obs >= 1:
        return "Confirmed"
    if n_obs >= 2:
        return "Probable"
    if n_obs == 1:
        return "Indicative"
    return "None"
