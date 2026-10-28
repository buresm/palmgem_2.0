"""Per-run task-timing history and slowdown detection.

Every pipeline run appends one JSON line per case to
``logs/<case_schema>_timings.jsonl`` (task -> seconds, total, status). Before
recording, the current run is compared against the median of the previous
successful runs, and any task slower than ``timings.slowdown_factor`` times
its median is warned about — so a performance regression is visible the day
it appears instead of after a 45-minute run (see the PG-51 optimisation
pass, all of which this would have flagged).
"""
import json
import os
from datetime import datetime
from statistics import median

from src.logger import debug, verbose, warning


def _history_file(cfg):
    return cfg.timings.history_file or os.path.join(
        'logs', f'{cfg.domain.case_schema}_timings.jsonl')


def load_history(cfg):
    """All recorded runs for this case, oldest first. Malformed lines are
    skipped so a corrupted line can never break a pipeline run."""
    path = _history_file(cfg)
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                debug('skipping malformed timings line in {}', path)
    return entries


def record_run(cfg, task_timings, status='ok'):
    """Append this run's timings to the per-case history. Returns the entry."""
    if not cfg.timings.enabled or not task_timings:
        return None

    entry = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': status,
        'tasks': {name: seconds for name, seconds in task_timings},
        'total': round(sum(seconds for _, seconds in task_timings), 1),
    }

    path = _history_file(cfg)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    verbose(f'task timings recorded to {path}')
    return entry


def baseline_medians(cfg, history=None):
    """{task: median seconds} over the previous *successful* runs."""
    if history is None:
        history = load_history(cfg)
    ok_runs = [e for e in history if e.get('status') == 'ok']
    per_task = {}
    for entry in ok_runs:
        for name, seconds in entry.get('tasks', {}).items():
            per_task.setdefault(name, []).append(seconds)
    return {name: median(vals) for name, vals in per_task.items()
            if len(vals) >= int(cfg.timings.min_history)}


def check_regressions(cfg, task_timings):
    """Warn about tasks much slower than their historical median.

    Small durations (< ``timings.min_seconds``) are ignored — fast tasks
    fluctuate by whole factors without meaning anything. Returns a list of
    {task, seconds, median, ratio} findings (empty = nothing suspicious).
    """
    if not cfg.timings.enabled or not task_timings:
        return []

    medians = baseline_medians(cfg)
    factor = float(cfg.timings.slowdown_factor)
    min_seconds = float(cfg.timings.min_seconds)

    findings = []
    for name, seconds in task_timings:
        med = medians.get(name)
        if med is None or med <= 0:
            continue
        if seconds >= min_seconds and seconds >= factor * med:
            ratio = seconds / med
            findings.append({'task': name, 'seconds': seconds,
                             'median': med, 'ratio': ratio})
            warning(f'task {name} took {seconds:.1f}s — {ratio:.1f}x its median '
                    f'of previous runs ({med:.1f}s); possible performance regression')

    if not findings:
        debug('task timings within historical range')
    return findings
