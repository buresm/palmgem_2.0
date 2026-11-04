# src/tasks/base.py
class BaseTask:
    """
    Base class for all tasks using attribute delegation.
    Any method called on Task that isn't defined here is
    automatically forwarded to the shared Database instance.
    """
    def __init__(self, name, cfg, db):
        self.name = name
        self.cfg = cfg
        self.db = db  # The persistent Database instance

    def __getattr__(self, name):
        """
        Dynamic proxy: if a method (like execute_batch) is called on
        the task but not defined, try to get it from the db object.
        """
        return getattr(self.db, name)

    def vacuum_case_tables(self, *tables, full=False):
        """VACUUM (ANALYZE) the named case-schema tables in the middle of a
        task, before a step that reads tables an earlier step rewrote
        (switch vacuum_analyze; missing tables are skipped). full=True
        compacts the table as well (after deleting most of its rows)."""
        if self.cfg.get('vacuum_analyze', True):
            self.db.vacuum_analyze(self.cfg.domain.case_schema, list(tables), full=full)

    def run(self):
        raise NotImplementedError