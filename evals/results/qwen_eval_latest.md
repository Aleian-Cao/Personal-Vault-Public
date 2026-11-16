# Qwen-assisted vs deterministic chat search: eval 20261112_144817

Synthetic only. 507 entries, 138 queries (dev 86 / held-out 52). Prompt `pv-intent-1`, backend `completion`, threads 8, timeout 10 s. Machine: Windows-11-10.0.26300-SP0, 16 logical CPUs, Python 3.14.6. Model sha256: `None`.

**Qwen was not available (or --skip-qwen): only deterministic numbers exist.**

## Results: heldout

| metric | deterministic |
|---|---|
| n | 52 |
| overall_correct_pct | 96.2 |
| acc_at_1_pct | 92.6 |
| acc_at_3_pct | 92.6 |
| ambiguity_handled_pct | 100.0 |
| none_correct_pct | 100.0 |
| wrong_account | 0 |
| wrong_when_exact | 0 |
| wrong_when_suggested | 0 |
| false_exact | 0 |
| numeric_violations | 0 |
| ai_calls | 0 |
| routes (det/qwen/fallback) | {'deterministic': 52, 'qwen': 0, 'fallback': 0} |
| answer latency ms p50 / p95 / max | 10.4 / 20.2 / 33.5 |

## Results: dev

| metric | deterministic |
|---|---|
| n | 86 |
| overall_correct_pct | 90.7 |
| acc_at_1_pct | 85.4 |
| acc_at_3_pct | 85.4 |
| ambiguity_handled_pct | 100.0 |
| none_correct_pct | 96.7 |
| wrong_account | 1 |
| wrong_when_exact | 0 |
| wrong_when_suggested | 1 |
| false_exact | 0 |
| numeric_violations | 0 |
| ai_calls | 0 |
| routes (det/qwen/fallback) | {'deterministic': 86, 'qwen': 0, 'fallback': 0} |
| answer latency ms p50 / p95 / max | 5.0 / 21.4 / 38.1 |

## Results: all

| metric | deterministic |
|---|---|
| n | 138 |
| overall_correct_pct | 92.8 |
| acc_at_1_pct | 88.0 |
| acc_at_3_pct | 88.0 |
| ambiguity_handled_pct | 100.0 |
| none_correct_pct | 98.0 |
| wrong_account | 1 |
| wrong_when_exact | 0 |
| wrong_when_suggested | 1 |
| false_exact | 0 |
| numeric_violations | 0 |
| ai_calls | 0 |
| routes (det/qwen/fallback) | {'deterministic': 138, 'qwen': 0, 'fallback': 0} |
| answer latency ms p50 / p95 / max | 7.8 / 21.4 / 38.1 |

Definitions: acc@1/acc@3 over queries whose gold is one entry; wrong_account = a wrong entry shown first (gold entry), any entry for a gold-none query, or an entry outside the gold set / an auto-selected one for gold-ambiguous; false_exact = status `exact` that is not the gold entry; numeric_violations = a returned entry whose account/alias lacks an explicit number from the query.

## Safety

| check | deterministic | qwen | fault-injection runner (None/garbage/oversized/crash) |
|---|---|---|---|
| secret leaks (canary passwords + master string in any prompt or returned payload) | 0 | None | 0 |
| crashes | 0 | None | 0 |

Fault injection: result entries identical to deterministic on 138/138 queries. The master-password canary is never passed to the pipeline, so its zero count only shows the code path does not invent it.

## Per group (overall correct %, all splits)

| group | deterministic |
|---|---|
| E01 | 100% (25) |
| E02 | 100% (22) |
| E03 | 100% (12) |
| E04 | 56% (18) |
| E05 | 95% (21) |
| E06 | 95% (20) |
| E08 | 100% (20) |
