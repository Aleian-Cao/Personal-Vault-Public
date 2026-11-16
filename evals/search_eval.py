"""Deterministic search reliability eval (SYNTHETIC only, Qwen OFF, no network).

Runs the pipeline with runner=None over
  * the original 138 queries (evals/fixtures/queries.json; ground truth UNCHANGED, dev 86 / held-out 52), and
  * the 34 confirmed red-team wrong-account cases (evals/fixtures/redteam_confirmed.json; used to drive the fix, so
    reported separately and never mixed into the held-out numbers).
Every query is placed in exactly one outcome:
  correct        = the eval's own `correct` flag (right entry first / none for gold none / a real choice for gold ambiguous)
  wrong_account  = the eval's own `wrong` flag (the failure to drive to zero)
  clarification  = not correct, not wrong, and the answer asks the user to choose (status ambiguous/suggested)
  abstain        = not correct, not wrong, and no entry is shown (status none)
Run: python evals/search_eval.py   -> evals/results/search_eval_<ts>.json and search_eval_latest.md
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('qwen_eval', HERE / 'qwen_eval.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
from personal_vault.core import norm  # noqa: E402  (path set up by qwen_eval)


def redteam_queries(entries):
    by_acc = {}
    for e in entries:
        by_acc.setdefault(e.account, e)
    out = []
    cases = [(c, 'redteam') for c in json.loads((HERE / 'fixtures' / 'redteam_confirmed.json').read_text(encoding='utf-8'))['cases']]
    cases += [(c, 'redteam2') for c in json.loads((HERE / 'fixtures' / 'redteam_r2_confirmed.json').read_text(encoding='utf-8'))['cases']]
    cases += [(c, 'redteam3') for c in json.loads((HERE / 'fixtures' / 'redteam_r3_confirmed.json').read_text(encoding='utf-8'))['cases']]
    cases += [(c, 'redteam4') for c in json.loads((HERE / 'fixtures' / 'redteam_r4_confirmed.json').read_text(encoding='utf-8'))['cases']]
    cases += [(c, 'redteam6') for c in json.loads((HERE / 'fixtures' / 'redteam_r6_confirmed.json').read_text(encoding='utf-8'))['cases']]
    cases += [(c, 'redteam7') for c in json.loads((HERE / 'fixtures' / 'redteam_r7_confirmed.json').read_text(encoding='utf-8'))['cases']]
    for c, split in cases:
        g = dict(c['gold'])
        if g['type'] == 'entry':
            g['name'] = by_acc[g['account']].name
        out.append({'id': c['id'], 'group': c['lens'], 'split': split, 'query': c['query'], 'prev': c['prev'], 'gold': g,
                    'nums': [t for t in norm(c['query']).split() if t.isdigit()]})
    return out


def outcome(r):
    if r.get('wrong'):
        return 'wrong_account'
    if r.get('correct'):
        return 'correct'
    return 'clarification' if r['status'] in ('ambiguous', 'suggested') else 'abstain'


def tally(recs):
    t = {'n': len(recs), 'correct': 0, 'wrong_account': 0, 'clarification': 0, 'abstain': 0}
    for r in recs:
        t[outcome(r)] += 1
    t['false_exact'] = sum(r.get('false_exact', False) for r in recs)
    t['numeric_violations'] = sum(r.get('num_violation', False) for r in recs)
    t['exact_answers'] = sum(r['status'] == 'exact' for r in recs)
    t['secret_leaks'] = sum(r.get('leaked', 0) for r in recs)
    ms = sorted(r['ms'] for r in recs)
    t['answer_ms_p50'] = round(ms[len(ms) // 2], 1)
    t['answer_ms_p95'] = round(ms[int(0.95 * (len(ms) - 1))], 1)
    assert t['correct'] + t['wrong_account'] + t['clarification'] + t['abstain'] == t['n']
    return t


def main():
    entries = ev.build_entries()
    base = ev.FIX['queries']
    red = redteam_queries(entries)
    t0 = time.perf_counter()
    res = ev.run_mode('deterministic-only', None, entries, base + red)
    recs = [r for r in res['records'] if 'error' not in r]
    sets = {
        'original 138 (all)': [r for r in recs if r['split'] in ('dev', 'heldout')],
        'original dev (86)': [r for r in recs if r['split'] == 'dev'],
        'original held-out (52)': [r for r in recs if r['split'] == 'heldout'],
        'red-team round 1 (34)': [r for r in recs if r['split'] == 'redteam'],
        'red-team round 2 (24)': [r for r in recs if r['split'] == 'redteam2'],
        'red-team round 3 (30)': [r for r in recs if r['split'] == 'redteam3'],
        'red-team round 4 (21)': [r for r in recs if r['split'] == 'redteam4'],
        'red-team round 6 (13)': [r for r in recs if r['split'] == 'redteam6'],
        'red-team round 7 (13)': [r for r in recs if r['split'] == 'redteam7'],
        f'ALL ({len(recs)})': recs,
    }
    summary = {k: tally(v) for k, v in sets.items()}
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bad = [r for r in recs if outcome(r) == 'wrong_account']
    report = {'timestamp': ts, 'runner': None, 'entries': len(entries), 'crashes': res['crashes'], 'summary': summary,
              'wrong_account_cases': [{k: r[k] for k in ('id', 'split', 'query', 'prev', 'gold', 'status', 'got')} for r in bad],
              'non_correct_non_wrong': [{k: r[k] for k in ('id', 'split', 'query', 'prev', 'gold', 'status', 'got')} | {'outcome': outcome(r)}
                                        for r in recs if outcome(r) in ('abstain', 'clarification')],
              'wall_s': round(time.perf_counter() - t0, 1)}
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    (out / f'search_eval_{ts}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    head = ['set', 'n (denominator)', 'correct', 'wrong_account', 'clarification', 'abstain', 'false_exact', 'numeric_viol', 'secret_leaks', 'p95 ms']
    rows = [[k, v['n'], v['correct'], v['wrong_account'], v['clarification'], v['abstain'], v['false_exact'], v['numeric_violations'], v['secret_leaks'], v['answer_ms_p95']]
            for k, v in summary.items()]
    md = [f'# Deterministic search eval {ts} (Qwen OFF, synthetic, {len(entries)} entries)\n', ev.md_table(rows, head), '']
    md.append('Outcomes are mutually exclusive and sum to n. `wrong_account` = the eval\'s own flag; `clarification` = not correct but asks the user to choose; '
              '`abstain` = no entry shown for a query whose gold was an entry/ambiguous set. Ground truth of the 138 original queries is unchanged.\n')
    md.append(f"## wrong_account cases ({len(bad)})\n" + ('\n'.join(f"- `{r['id']}` {json.dumps(r['query'], ensure_ascii=False)} gold={r['gold']} got {r['status']} {r['got'][:2]}" for r in bad) or '- none'))
    non = [r for r in recs if outcome(r) in ('abstain', 'clarification') and r['split'] in ('dev', 'heldout')]
    md.append(f"\n## Not correct but safe on the original 138 ({len(non)}): abstain / clarification\n" +
              '\n'.join(f"- `{r['id']}` ({r['split']}, {outcome(r)}) {json.dumps(r['query'], ensure_ascii=False)} gold={r['gold'].get('account') or r['gold']['type']} -> {r['status']} {r['got'][:2]}" for r in non))
    (out / 'search_eval_latest.md').write_text('\n'.join(md), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(md))
    return 0 if not bad and not res['crashes'] else 1


if __name__ == '__main__':
    sys.exit(main())
