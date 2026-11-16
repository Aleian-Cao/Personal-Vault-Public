"""Run the pipeline on a LOCKED blind held-out fixture and report outcomes by lens (SYNTHETIC only, Qwen OFF).

  python evals/heldout_eval.py [--fixture evals/fixtures/heldout_blind_v2.json] [--tag first_run]

Refuses to run if the fixture's SHA-256 differs from its .sha256 lock file (gold must not change after locking).
Outcomes are mutually exclusive: correct / wrong_account / clarification / abstain (same definitions as search_eval.py).
`false_exact` = status exact that is not exactly the gold entry. Held-out results are never to be used for tuning.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('qwen_eval', HERE / 'qwen_eval.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
from personal_vault.core import norm  # noqa: E402


def outcome(r):
    if r.get('wrong'):
        return 'wrong_account'
    if r.get('correct'):
        return 'correct'
    return 'clarification' if r['status'] in ('ambiguous', 'suggested') else 'abstain'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', default=str(HERE / 'fixtures' / 'heldout_blind_v2.json'))
    ap.add_argument('--tag', default='run')
    a = ap.parse_args()
    fx_path = Path(a.fixture)
    raw = fx_path.read_text(encoding='utf-8')
    lock = fx_path.with_suffix('.sha256').read_text(encoding='utf-8').split()[0].upper()
    got = hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()
    if got != lock:
        print(f'REFUSING: fixture hash {got} != lock {lock} (gold changed after locking)', file=sys.stderr)
        return 2
    entries = ev.build_entries()
    by_acc = {}
    for e in entries:
        by_acc.setdefault(e.account, e)
    queries = []
    for c in json.loads(raw)['cases']:
        g = dict(c['gold'])
        if g['type'] == 'entry':
            g['name'] = by_acc[g['account']].name
        queries.append({'id': c['id'], 'group': c['lens'], 'split': 'heldout_v2', 'query': c['query'], 'prev': c['prev'], 'gold': g,
                        'nums': [t for t in norm(c['query']).split() if t.isdigit()]})
    res = ev.run_mode('deterministic-only', None, entries, queries)
    recs = [r for r in res['records'] if 'error' not in r]
    for r in recs:
        r['outcome'] = outcome(r)

    def tally(rs):
        t = {'n': len(rs)}
        for k in ('correct', 'wrong_account', 'clarification', 'abstain'):
            t[k] = sum(r['outcome'] == k for r in rs)
        t['false_exact'] = sum(r.get('false_exact', False) for r in rs)
        t['numeric_viol'] = sum(r.get('num_violation', False) for r in rs)
        t['exact_answers'] = sum(r['status'] == 'exact' for r in rs)
        return t

    total = tally(recs)
    by_lens = {l: tally([r for r in recs if r['group'] == l]) for l in sorted({r['group'] for r in recs})}
    by_gold = {g: tally([r for r in recs if r['gold']['type'] == g]) for g in ('entry', 'none', 'ambiguous')}
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = {'timestamp': ts, 'tag': a.tag, 'fixture_sha256': got, 'crashes': res['crashes'], 'total': total, 'by_lens': by_lens, 'by_gold_type': by_gold,
              'wrong_account': [{k: r[k] for k in ('id', 'group', 'query', 'prev', 'gold', 'status', 'got')} for r in recs if r['outcome'] == 'wrong_account'],
              'false_exact': [{k: r[k] for k in ('id', 'group', 'query', 'prev', 'gold', 'status', 'got')} for r in recs if r.get('false_exact')],
              'records': recs}
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    (out / f'heldout_{a.tag}_{ts}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    head = ['set', 'n', 'correct', 'wrong_account', 'clarification', 'abstain', 'false_exact', 'exact answers']
    rows = [['**ALL**', *[total[k] for k in ('n', 'correct', 'wrong_account', 'clarification', 'abstain', 'false_exact', 'exact_answers')]]]
    rows += [[f'lens: {l}', *[t[k] for k in ('n', 'correct', 'wrong_account', 'clarification', 'abstain', 'false_exact', 'exact_answers')]] for l, t in by_lens.items()]
    rows += [[f'gold: {g}', *[t[k] for k in ('n', 'correct', 'wrong_account', 'clarification', 'abstain', 'false_exact', 'exact_answers')]] for g, t in by_gold.items()]
    sys.stdout.reconfigure(encoding='utf-8')
    print(f'# Held-out {a.tag} {ts} fixture {got[:12]} crashes={res["crashes"]}\n')
    print(ev.md_table(rows, head))
    print(f"\nwrong_account ({len(report['wrong_account'])}), false_exact ({len(report['false_exact'])}) listed in the json.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
