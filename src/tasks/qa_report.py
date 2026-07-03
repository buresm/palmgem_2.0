"""QA report task: one self-contained HTML per case.

Collects map thumbnails + histograms and statistics for every variable in the
written driver NetCDF files, PIDS compliance findings, landcover/building
statistics from the case schema, and the per-task timings of the current run,
and renders them into a single HTML file (images embedded base64) under
``output/``.
"""
import base64
import io
import os
from datetime import datetime
from html import escape

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .base import BaseTask
from src.logger import progress, debug, verbose, warning
from src.utils.pids import load_pids_spec, validate_file

# variables plotted per figure cap — a runaway file cannot hang the report
MAX_PLOTTED_VARS = 60
# histogram sample cap so 3-D variables do not dominate runtime
MAX_HIST_SAMPLES = 500_000


def _var_stats(values):
    """Stats dict for a (possibly masked) numeric array."""
    arr = np.ma.masked_invalid(np.ma.asarray(values))
    total = arr.size
    filled = int(np.ma.count_masked(arr))
    data = arr.compressed()
    if data.size == 0:
        return {'count': total, 'fill_fraction': 1.0,
                'min': None, 'max': None, 'mean': None, 'std': None}
    return {
        'count': total,
        'fill_fraction': filled / total if total else 0.0,
        'min': float(data.min()),
        'max': float(data.max()),
        'mean': float(data.mean()),
        'std': float(data.std()),
    }


def _fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def _plot_variable(name, data2d, hist_values, long_name=''):
    """Map + histogram figure for one variable; returns base64 PNG."""
    fig, (ax_map, ax_hist) = plt.subplots(
        1, 2, figsize=(7.5, 3.0), gridspec_kw={'width_ratios': [1.2, 1.0]})

    im = ax_map.imshow(data2d, origin='lower', cmap='viridis', aspect='equal')
    fig.colorbar(im, ax=ax_map, shrink=0.85)
    ax_map.set_title(name, fontsize=9)
    ax_map.tick_params(labelsize=6)

    if hist_values.size:
        ax_hist.hist(hist_values, bins=40, color='#4878a8')
    ax_hist.set_title(long_name[:48] or 'distribution', fontsize=8)
    ax_hist.tick_params(labelsize=6)

    return _fig_to_base64(fig)


def collect_file_section(path, driver, pids_spec=None):
    """All report content for one driver file: dims, global attrs, per-variable
    stats + thumbnails, and PIDS findings. Returns a dict; raises OSError when
    the file is unreadable (caller degrades gracefully)."""
    import netCDF4

    section = {'path': path, 'driver': driver, 'dims': [], 'global_attrs': [],
               'variables': [], 'pids': []}

    with netCDF4.Dataset(path, 'r') as ds:
        section['dims'] = [(name, len(dim)) for name, dim in ds.dimensions.items()]
        section['global_attrs'] = [(a, str(ds.getncattr(a))) for a in ds.ncattrs()]

        plotted = 0
        for vn, var in ds.variables.items():
            entry = {'name': vn, 'dims': '×'.join(var.dimensions),
                     'dtype': str(var.dtype), 'stats': None, 'image': None}
            if var.dtype.kind in 'fiu' and var.ndim >= 1:
                values = var[:]
                entry['stats'] = _var_stats(values)

                if var.ndim >= 2 and plotted < MAX_PLOTTED_VARS:
                    data2d = values[0] if var.ndim > 2 else values
                    # np.ma arrays plot with masked cells blank, which is what
                    # we want for fill values
                    hist_values = np.ma.masked_invalid(np.ma.asarray(values)).compressed()
                    if hist_values.size > MAX_HIST_SAMPLES:
                        hist_values = hist_values[::hist_values.size // MAX_HIST_SAMPLES]
                    label = getattr(var, 'long_name', '')
                    if var.ndim > 2:
                        entry['slice_note'] = 'level 0 shown'
                    entry['image'] = _plot_variable(vn, data2d, hist_values, label)
                    plotted += 1
            section['variables'].append(entry)

    if pids_spec is not None:
        section['pids'] = validate_file(path, pids_spec, driver)

    return section


def _fmt(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.4g}'
    return escape(str(value))


def render_report(context):
    """Render the collected context dict into a self-contained HTML string."""
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        f"<title>PALM-GeM QA report — {escape(context['case'])}</title>",
        '<style>'
        'body{font-family:sans-serif;margin:2em;color:#222;max-width:70em}'
        'h1{border-bottom:2px solid #4878a8}h2{margin-top:2em;color:#2a4a68}'
        'table{border-collapse:collapse;margin:0.6em 0}'
        'td,th{border:1px solid #bbb;padding:3px 9px;font-size:0.85em;text-align:left}'
        'th{background:#e8eef4}'
        '.err{background:#fbdcdc}.warn{background:#fdf3d8}.ok{color:#2c7a2c}'
        'img{border:1px solid #ddd;margin:2px 0}'
        '.varblock{margin-bottom:0.4em}'
        '</style></head><body>',
        f"<h1>PALM-GeM QA report — {escape(context['case'])}</h1>",
        f"<p>generated {escape(context['generated'])}</p>",
    ]

    # domain / meta
    parts.append('<h2>Domain</h2><table>')
    for key, val in context.get('meta', []):
        parts.append(f'<tr><th>{escape(key)}</th><td>{_fmt(val)}</td></tr>')
    parts.append('</table>')

    # database sections
    if context.get('landcover_shares'):
        parts.append('<h2>Landcover composition (case schema)</h2>'
                     '<table><tr><th>type</th><th>polygons</th><th>area share</th></tr>')
        for row in context['landcover_shares']:
            parts.append(f'<tr><td>{row[0]}</td><td>{row[1]}</td>'
                         f'<td>{row[2] * 100:.1f} %</td></tr>')
        parts.append('</table>')

    if context.get('building_stats'):
        parts.append('<h2>Buildings</h2><table>')
        for key, val in context['building_stats']:
            parts.append(f'<tr><th>{escape(key)}</th><td>{_fmt(val)}</td></tr>')
        parts.append('</table>')

    # driver files
    for sec in context.get('files', []):
        parts.append(f"<h2>Driver: {escape(os.path.basename(sec['path']))}</h2>")
        parts.append('<table><tr><th>dimension</th><th>size</th></tr>')
        for name, size in sec['dims']:
            parts.append(f'<tr><td>{escape(name)}</td><td>{size}</td></tr>')
        parts.append('</table>')

        if sec['pids']:
            parts.append('<h3>PIDS findings</h3><table><tr><th>level</th><th>message</th></tr>')
            for f in sec['pids']:
                cls = 'err' if f.level == 'error' else 'warn'
                parts.append(f'<tr class="{cls}"><td>{f.level}</td>'
                             f'<td>{escape(f.message)}</td></tr>')
            parts.append('</table>')
        else:
            parts.append('<p class="ok">PIDS check: no findings.</p>')

        parts.append('<h3>Variables</h3>')
        parts.append('<table><tr><th>variable</th><th>dims</th><th>dtype</th>'
                     '<th>min</th><th>max</th><th>mean</th><th>fill</th></tr>')
        for v in sec['variables']:
            s = v['stats'] or {}
            fill = f"{s.get('fill_fraction', 0) * 100:.1f} %" if s else '—'
            parts.append(
                f"<tr><td>{escape(v['name'])}</td><td>{escape(v['dims'])}</td>"
                f"<td>{escape(v['dtype'])}</td><td>{_fmt(s.get('min'))}</td>"
                f"<td>{_fmt(s.get('max'))}</td><td>{_fmt(s.get('mean'))}</td>"
                f"<td>{fill}</td></tr>")
        parts.append('</table>')

        for v in sec['variables']:
            if v.get('image'):
                note = f" <i>({v['slice_note']})</i>" if v.get('slice_note') else ''
                parts.append(f'<div class="varblock"><b>{escape(v["name"])}</b>{note}<br>'
                             f'<img src="data:image/png;base64,{v["image"]}"></div>')

        parts.append('<h3>Global attributes</h3><table>')
        for attr, val in sec['global_attrs']:
            parts.append(f'<tr><th>{escape(attr)}</th><td>{escape(val)}</td></tr>')
        parts.append('</table>')

    # timings
    if context.get('timings'):
        parts.append('<h2>Task timings (this run)</h2>'
                     '<table><tr><th>task</th><th>seconds</th></tr>')
        for name, seconds in context['timings']:
            parts.append(f'<tr><td>{escape(name)}</td><td>{seconds}</td></tr>')
        parts.append('</table>')

    parts.append('</body></html>')
    return '\n'.join(parts)


class QaReportTask(BaseTask):
    """Produce the per-case HTML QA report (see module docstring)."""

    def run(self):
        case = self.cfg.domain.case_schema
        context = {
            'case': case,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'meta': self._meta(),
            'files': [],
            'timings': self.cfg._settings.get('task_timings', []),
        }

        try:
            pids_spec = load_pids_spec(self.cfg)
        except FileNotFoundError as e:
            warning(f'qa_report: {e}; PIDS section will be empty')
            pids_spec = None

        for driver, path in (('static', self.cfg.domain.static_driver_file),
                             ('slurb', self.cfg.domain.slurb_driver_file)):
            if not path or not os.path.exists(path):
                continue
            progress('qa_report: analysing {} driver {}', driver, path)
            try:
                context['files'].append(collect_file_section(path, driver, pids_spec))
            except OSError as e:
                warning(f'qa_report: cannot read {path}: {e}; skipping')

        context['landcover_shares'] = self._landcover_shares()
        context['building_stats'] = self._building_stats()

        report_file = self.cfg.qa_report.report_file or os.path.join(
            'output', f'{case}_qa_report.html')
        os.makedirs(os.path.dirname(report_file) or '.', exist_ok=True)

        html = render_report(context)
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html)
        progress('qa_report written: {} ({} driver file(s), {} kB)',
                 report_file, len(context['files']), len(html) // 1024)

    # --- collection helpers -------------------------------------------------

    def _table_exists(self, table):
        return bool(self.fetchone(
            'select exists(select 1 from information_schema.tables '
            'where table_schema = %s and table_name = %s)',
            (self.cfg.domain.case_schema, table)))

    def _meta(self):
        d = self.cfg.domain
        return [
            ('case schema', d.case_schema),
            ('grid', f'{d.nx} × {d.ny} cells @ {d.dx} × {d.dy} m'),
            ('dz', d.dz),
            ('centre (palm srid)', f'{d.cent_x}, {d.cent_y}'),
            ('srid_palm', self.cfg.srid_palm),
            ('input schema', self.cfg.input_schema),
        ]

    def _landcover_shares(self):
        table = self.cfg.tables.landcover
        if not self._table_exists(table):
            verbose('qa_report: no landcover table in case schema; skipping shares')
            return []
        rows = self.fetch(
            f'select type, count(*), sum(st_area(geom)) '
            f'from "{self.cfg.domain.case_schema}"."{table}" group by type order by type')
        total = sum(r[2] or 0 for r in rows) or 1.0
        return [(r[0], r[1], (r[2] or 0) / total) for r in rows]

    def _building_stats(self):
        table = self.cfg.tables.buildings_grid
        if not self._table_exists(table):
            verbose('qa_report: no buildings_grid table; skipping building stats')
            return []
        row = self.fetch(
            f'select count(*), min(height), round(avg(height)::numeric, 1), max(height) '
            f'from "{self.cfg.domain.case_schema}"."{table}"')[0]
        return [
            ('building grid cells', row[0]),
            ('height min (m)', row[1]),
            ('height mean (m)', row[2]),
            ('height max (m)', row[3]),
        ]
