import os

from .base import BaseTask
from src.logger import progress, warning
from src.utils.pids import run_pids_check


class PidsCheckTask(BaseTask):
    """Standalone PIDS compliance validation of already-written driver files.

    The same validation runs automatically right after each driver is written
    (gated by ``pids.enabled``); this task re-validates existing output files
    without regenerating them — useful in staged runs or after manual edits.
    """

    def run(self):
        candidates = [
            ('static', self.cfg.domain.static_driver_file),
            ('slurb', self.cfg.domain.slurb_driver_file),
        ]

        checked = 0
        for driver, path in candidates:
            if not path or not os.path.exists(path):
                continue
            run_pids_check(self.cfg, path, driver, force=True)
            checked += 1

        if checked == 0:
            warning('pids_check: no driver files found to validate '
                    f'({[p for _, p in candidates]})')
        else:
            progress('pids_check validated {} driver file(s)', checked)
