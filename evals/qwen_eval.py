"""Deterministic-only vs Qwen-assisted eval of the chat-search pipeline (SYNTHETIC data only, no network).

Run:  python evals/qwen_eval.py [--skip-qwen] [--timeout 10]
Writes evals/results/qwen_eval_<timestamp>.json and evals/results/qwen_eval_latest.md.
Prompt tuning (if any) may only use split=dev; split=heldout is reported separately and never used for tuning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'sidecar'))

from chat_pipeline import ChatPipeline  # noqa: E402
from qwen_runner import PROMPT_VERSION, QwenRunner  # noqa: E402
from personal_vault.core import Entry, norm, synthetic_entries  # noqa: E402

FIX = json.loads((HERE / 'fixtures' / 'queries.json').read_text(encoding='utf-8'))
MASTER = FIX['master_password_canary']  # never given to the pipeline; scanned for anyway


def build_entries():
    extra = [Entry.new(d['account'], d['name'], d['password'], d['aliases'], d['description'], d['tags'], d['url']) for d in FIX['extra_entries']]
    return synthetic_entries(500) + extra


class FaultyRunner:
    """E07: unavailable / timeout / garbage / crash. Cycles through failure modes."""

    def __init__(self):
        self.calls, self.prompt_log, self.last_latency_ms = 0, [], 0

    def extract_intent(self, question, prev_intent=None):
        self.calls += 1
        mode = self.calls % 4
        if mode == 0:
            raise RuntimeError('worker crashed')
        return [None, {'intent': 'find_account', 'query': 'x' * 300}, {'intent': 'rm -rf', 'query': 'etap'}][mode - 1]


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 1)


def stats(xs):
    return {'n': len(xs), 'p50': pct(xs, 50), 'p95': pct(xs, 95), 'max': round(max(xs), 1) if xs else None}


def score(gold, res, nums, by_key):
    ents = res['entries']
    keys = [(e['account'], e['name']) for e in ents]
    exact = res['status'] == 'exact'
    t = gold['type']
    out = {'top1': False, 'top3': False, 'wrong': False, 'false_exact': False, 'correct': False}
    if t == 'entry':
        k = (gold['account'], gold['name'])
        out['top1'], out['top3'] = bool(keys) and keys[0] == k, k in keys[:3]
        out['wrong'] = bool(keys) and keys[0] != k
        out['false_exact'] = exact and keys != [k]
        out['correct'] = out['top1']
    elif t == 'none':
        out['correct'], out['wrong'], out['false_exact'] = not keys, bool(keys), exact
    else:
        allowed = set(gold['accounts'] or [e['account'] for e in ents])
        out['correct'] = res['status'] == 'ambiguous' and len(ents) >= 2 and all(e['account'] in allowed for e in ents)
        out['wrong'] = any(e['account'] not in allowed for e in ents) or exact
        out['false_exact'] = exact
    out['num_violation'] = bool(nums) and any(
        not any(set(nums) <= set(norm(i).split()) for i in (e['account'], *e['aliases'])) for e in ents)
    return out


def run_mode(name, runner, entries, queries):
    by_key = {(e.account, e.name): e for e in entries}
    canaries = [e.password for e in entries] + [MASTER]
    recs, leaks, crashes = [], 0, 0
    for q in queries:
        pipe = ChatPipeline(runner)
        c0, p0 = getattr(runner, 'calls', 0), len(getattr(runner, 'prompt_log', []))
        try:
            for prev in q['prev']:
                pipe.answer(prev, entries)
            t0 = time.perf_counter()
            res = pipe.answer(q['query'], entries)
            wall = (time.perf_counter() - t0) * 1000
        except Exception as e:  # noqa: BLE001
            crashes += 1
            recs.append({'id': q['id'], 'error': type(e).__name__})
            continue
        prompts = getattr(runner, 'prompt_log', [])[p0:]
        blob = json.dumps(res, ensure_ascii=False) + '\n'.join(prompts)
        leaked = sum(blob.count(c) for c in canaries)
        leaks += leaked
        sc = score(q['gold'], res, q['nums'], by_key)
        recs.append({'id': q['id'], 'group': q['group'], 'split': q['split'], 'query': q['query'], 'prev': q['prev'], 'gold': q['gold'],
                     'route': res['route'], 'status': res['status'], 'got': [e['account'] for e in res['entries']][:5],
                     'action': res['suggested_action'], 'ai_calls': getattr(runner, 'calls', 0) - c0, 'ms': round(wall, 1),
                     'qwen_ms': getattr(runner, 'last_latency_ms', 0) if getattr(runner, 'calls', 0) > c0 else None,
                     'tps': getattr(runner, 'last_tokens_per_s', None) if getattr(runner, 'calls', 0) > c0 else None,
                     'rss_mb': getattr(runner, 'last_peak_rss_mb', None) if getattr(runner, 'calls', 0) > c0 else None,
                     'leaked': leaked, **sc})
    return {'name': name, 'records': recs, 'leaks': leaks, 'crashes': crashes}


def summarize(recs, split=None):
    r = [x for x in recs if 'error' not in x and (split is None or x['split'] == split)]
    ent = [x for x in r if x['gold']['type'] == 'entry']
    amb = [x for x in r if x['gold']['type'] == 'ambiguous']
    non = [x for x in r if x['gold']['type'] == 'none']
    pr = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    qms = [x['qwen_ms'] for x in r if x['qwen_ms']]
    routes = {k: sum(x['route'] == k for x in r) for k in ('deterministic', 'qwen', 'fallback')}
    return {
        'n': len(r), 'overall_correct_pct': pr(sum(x['correct'] for x in r), len(r)),
        'entry_n': len(ent), 'acc_at_1_pct': pr(sum(x['top1'] for x in ent), len(ent)), 'acc_at_3_pct': pr(sum(x['top3'] for x in ent), len(ent)),
        'ambiguous_n': len(amb), 'ambiguity_handled_pct': pr(sum(x['correct'] for x in amb), len(amb)),
        'none_n': len(non), 'none_correct_pct': pr(sum(x['correct'] for x in non), len(non)),
        'wrong_account': sum(x['wrong'] for x in r), 'wrong_when_exact': sum(x['wrong'] and x['status'] == 'exact' for x in r),
        'wrong_when_suggested': sum(x['wrong'] and x['status'] == 'suggested' for x in r), 'false_exact': sum(x['false_exact'] for x in r),
        'numeric_violations': sum(x['num_violation'] for x in r), 'routes': routes, 'ai_calls': sum(x['ai_calls'] for x in r),
        'answer_ms': stats([x['ms'] for x in r]), 'qwen_call_ms': stats(qms),
        'deterministic_route_ms': stats([x['ms'] for x in r if x['route'] == 'deterministic']),
    }



def model_sha(path):
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for blk in iter(lambda: f.read(1 << 22), b''):
                h.update(blk)
        return h.hexdigest()
    except OSError:
        return None


def md_table(rows, head):
    return '\n'.join(['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)] + ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-qwen', action='store_true')
    ap.add_argument('--timeout', type=float, default=10)
    a = ap.parse_args()
    entries = build_entries()
    queries = FIX['queries']
    det = run_mode('deterministic-only', None, entries, queries)
    runner = QwenRunner(timeout_s=a.timeout)
    have = runner.available() and not a.skip_qwen
    qw = run_mode('qwen-assisted', runner, entries, queries) if have else None
    faulty = FaultyRunner()
    fault = run_mode('fault-injection', faulty, entries, queries)

    modes = {'deterministic': det, **({'qwen': qw} if qw else {})}
    summ = {m: {s: summarize(v['records'], None if s == 'all' else s) for s in ('dev', 'heldout', 'all')} for m, v in modes.items()}
    # fault injection must equal deterministic on everything that did not need the model, and never crash or leak
    fault_same = sum(1 for d, f in zip(det['records'], fault['records']) if 'error' not in f and d['got'] == f['got'] or (f.get('got') == [] and d['got'] == []))
    cold_warm = {}
    if qw:
        q_ms = [x['qwen_ms'] for x in qw['records'] if x.get('qwen_ms')]
        cold_warm = {'first_call_ms': q_ms[0] if q_ms else None, 'warm': stats(q_ms[1:]),
                     'tokens_per_s_mean': round(statistics.mean([x['tps'] for x in qw['records'] if x.get('tps')]), 1) if any(x.get('tps') for x in qw['records']) else None,
                     'child_peak_rss_mb_max': max([x['rss_mb'] for x in qw['records'] if x.get('rss_mb')] or [None])}
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = {
        'timestamp': ts, 'machine': {'platform': platform.platform(), 'cpu_count': os.cpu_count(), 'python': sys.version.split()[0]},
        'config': {'prompt_version': PROMPT_VERSION, 'timeout_s': a.timeout, 'threads': runner.threads, 'backend': runner._backend(),
                   'model_path': runner.model_path, 'model_sha256': model_sha(runner.model_path) if have else None,
                   'entries': len(entries), 'queries': len(queries), 'dev': sum(q['split'] == 'dev' for q in queries),
                   'heldout': sum(q['split'] == 'heldout' for q in queries)},
        'summary': summ, 'cold_warm': cold_warm,
        'secret_leaks': {'deterministic': det['leaks'], 'qwen': qw['leaks'] if qw else None, 'fault_injection': fault['leaks']},
        'crashes': {'deterministic': det['crashes'], 'qwen': qw['crashes'] if qw else None, 'fault_injection': fault['crashes']},
        'fault_injection_same_entries_as_deterministic': f'{fault_same}/{len(queries)}',
        'records': {m: v['records'] for m, v in modes.items()},
    }
    res_dir = HERE / 'results'
    res_dir.mkdir(exist_ok=True)
    (res_dir / f'qwen_eval_{ts}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    (res_dir / 'qwen_eval_latest.md').write_text(render_md(report, det, qw, have), encoding='utf-8')
    print((res_dir / 'qwen_eval_latest.md').read_text(encoding='utf-8'))


def render_md(rep, det, qw, have):
    S, L = rep['summary'], []
    c = rep['config']
    L.append(f"# Qwen-assisted vs deterministic chat search: eval {rep['timestamp']}\n")
    L.append(f"Synthetic only. {c['entries']} entries, {c['queries']} queries (dev {c['dev']} / held-out {c['heldout']}). Prompt `{c['prompt_version']}`, "
             f"backend `{c['backend']}`, threads {c['threads']}, timeout {c['timeout_s']} s. Machine: {rep['machine']['platform']}, {rep['machine']['cpu_count']} logical CPUs, "
             f"Python {rep['machine']['python']}. Model sha256: `{c['model_sha256']}`.\n")
    if not have:
        L.append('**Qwen was not available (or --skip-qwen): only deterministic numbers exist.**\n')
    for split in ('heldout', 'dev', 'all'):
        L.append(f'## Results: {split}\n')
        keys = ['n', 'overall_correct_pct', 'acc_at_1_pct', 'acc_at_3_pct', 'ambiguity_handled_pct', 'none_correct_pct', 'wrong_account', 'wrong_when_exact', 'wrong_when_suggested',
                'false_exact', 'numeric_violations', 'ai_calls']
        rows = [[k] + [S[m][split][k] for m in S] for k in keys]
        rows.append(['routes (det/qwen/fallback)'] + [S[m][split]['routes'] for m in S])
        rows.append(['answer latency ms p50 / p95 / max'] + [f"{S[m][split]['answer_ms']['p50']} / {S[m][split]['answer_ms']['p95']} / {S[m][split]['answer_ms']['max']}" for m in S])
        L.append(md_table(rows, ['metric'] + list(S)) + '\n')
    L.append('Definitions: acc@1/acc@3 over queries whose gold is one entry; wrong_account = a wrong entry shown first (gold entry), any entry for a gold-none query, '
             'or an entry outside the gold set / an auto-selected one for gold-ambiguous; false_exact = status `exact` that is not the gold entry; '
             'numeric_violations = a returned entry whose account/alias lacks an explicit number from the query.\n')
    if qw:
        cw = rep['cold_warm']
        a = S['qwen']['all']
        L.append('## Qwen calls (latency, speed, memory)\n')
        L.append(md_table([['cold: first call (model read from disk, includes process + load), ms', cw['first_call_ms']],
                           ['warm calls ms p50 / p95 / max', f"{cw['warm']['p50']} / {cw['warm']['p95']} / {cw['warm']['max']} (n={cw['warm']['n']})"],
                           ['generation tokens/s (mean)', cw['tokens_per_s_mean']],
                           ['child peak working set MB (max; includes mmap of the 0.64 GB GGUF)', cw['child_peak_rss_mb_max']],
                           ['answer() latency on deterministic route ms p50 / p95 / max', f"{a['deterministic_route_ms']['p50']} / {a['deterministic_route_ms']['p95']} / {a['deterministic_route_ms']['max']}"]],
                          ['item', 'value']) + '\n')
        L.append('One-shot process per call: every call reloads the model (OS file cache is warm after the first). "Cold" here is only the first call of this run, '
                 'the file may already have been in the OS cache; a truly cold boot-time read was not measured.\n')
    L.append('## Safety\n')
    L.append(md_table([['secret leaks (canary passwords + master string in any prompt or returned payload)', rep['secret_leaks']['deterministic'],
                        rep['secret_leaks']['qwen'], rep['secret_leaks']['fault_injection']],
                       ['crashes', rep['crashes']['deterministic'], rep['crashes']['qwen'], rep['crashes']['fault_injection']]],
                      ['check', 'deterministic', 'qwen', 'fault-injection runner (None/garbage/oversized/crash)']) + '\n')
    L.append(f"Fault injection: result entries identical to deterministic on {rep['fault_injection_same_entries_as_deterministic']} queries. "
             'The master-password canary is never passed to the pipeline, so its zero count only shows the code path does not invent it.\n')
    L.append('## Per group (overall correct %, all splits)\n')
    groups = sorted({r['group'] for r in det['records'] if 'group' in r})
    rows = []
    for g in groups:
        row = [g]
        for m in (det, qw) if qw else (det,):
            rs = [r for r in m['records'] if r.get('group') == g]
            row.append(f"{round(100 * sum(r['correct'] for r in rs) / len(rs))}% ({len(rs)})")
        rows.append(row)
    L.append(md_table(rows, ['group', 'deterministic'] + (['qwen'] if qw else [])) + '\n')
    if qw:
        dmap = {r['id']: r for r in det['records'] if 'id' in r and 'group' in r}
        helped = [(r, dmap[r['id']]) for r in qw['records'] if 'group' in r and r['correct'] and not dmap[r['id']]['correct']]
        hurt = [(r, dmap[r['id']]) for r in qw['records'] if 'group' in r and not r['correct'] and dmap[r['id']]['correct']]
        both_wrong = [r for r in qw['records'] if 'group' in r and not r['correct'] and not dmap[r['id']]['correct']]

        def fmt(r, d):
            return f"- `{r['id']}` ({r['split']}) {json.dumps(r['query'], ensure_ascii=False)} gold={r['gold'].get('account') or r['gold']['type']}; det: {d['status']} {d['got'][:2]}; qwen: {r['route']}/{r['status']} {r['got'][:2]}"

        L.append(f'## Where Qwen helped ({len(helped)})\n' + '\n'.join(fmt(r, d) for r, d in helped) + '\n')
        L.append(f'## Where Qwen hurt ({len(hurt)})\n' + ('\n'.join(fmt(r, d) for r, d in hurt) or '- none') + '\n')
        L.append(f'## Wrong in both modes ({len(both_wrong)})\n' + '\n'.join(f"- `{r['id']}` ({r['split']}) {json.dumps(r['query'], ensure_ascii=False)} gold={r['gold'].get('account') or r['gold']['type']}; got {r['route']}/{r['status']} {r['got'][:2]}" for r in both_wrong) + '\n')
        h, d_ = S['qwen']['heldout'], S['deterministic']['heldout']
        w95 = rep['cold_warm']['warm']['p95']
        delta = (h['overall_correct_pct'] or 0) - (d_['overall_correct_pct'] or 0)
        L.append('## Verdict (rule-based, computed from the numbers above)\n')
        issues = []
        if h['wrong_account'] or S['qwen']['dev']['wrong_account']:
            issues.append(f"wrong-account answers exist (qwen dev {S['qwen']['dev']['wrong_account']}, held-out {h['wrong_account']}; deterministic held-out {d_['wrong_account']}): acceptance requires 0")
        if h['numeric_violations'] or S['qwen']['dev']['numeric_violations']:
            issues.append('numeric identity violations exist')
        if rep['secret_leaks']['qwen']:
            issues.append('secret leaks exist')
        if delta < 5:
            issues.append(f'held-out overall correctness improves by only {delta:+.1f} points (< +5): not a clear improvement')
        if w95 is not None and w95 > 3000:
            issues.append(f'warm p95 {w95} ms exceeds the 3000 ms target')
        L.append(('- Held-out overall correctness: deterministic %s%% vs Qwen-assisted %s%% (%+.1f points). Warm Qwen p95 %s ms.\n' % (d_['overall_correct_pct'], h['overall_correct_pct'], delta, w95)))
        L.append('- ' + ('; '.join(issues) + '.\n- **Recommendation: keep the deterministic path as the default and do not approve AI integration on this evidence.**' if issues
                         else 'No blocking issue under the stated thresholds; still validate on a larger held-out set before approval.') + '\n')
    return '\n'.join(L)


if __name__ == '__main__':
    main()
