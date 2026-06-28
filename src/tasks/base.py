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

    def run(self):
        raise NotImplementedError