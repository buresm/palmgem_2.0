from argparse import ArgumentParser
from src.config_loader import load_config
from src.logger import setup_logging, progress, error, warning
from src.tasks.factory import TaskFactory
# from src.tasks.setup import SetupTask
# from src.tasks.finalize import FinalizeTask
# from src.tasks.initialize_domain import InitializeDomainTask
# from src.tasks.netcdf_generator import StaticDriverGen
# from src.tasks.gis_importer import GisImporter
from src.database import Database

def main(args=None):
    # 1. Load Config
    config_file = args.config
    cfg = load_config(config_file)

    # 2. Setup Logging
    setup_logging(cfg)

    # 3. Connect to postgres
    db = Database(cfg.database._settings, cfg.pg_owner)

    # 4. Identify Tasks — setup and finalize are always run explicitly
    all_tasks = cfg.run_tasks if isinstance(cfg.run_tasks, list) else [cfg.run_tasks]
    tasks_to_run = [t for t in all_tasks if t not in ('setup', 'finalize')]

    progress(f"Initialized workflow for tasks: {tasks_to_run}")

    factory = TaskFactory(cfg, db)

    # Tasks run sequentially and later tasks depend on the schema state left by
    # earlier ones, so a failure is fatal: abort the pipeline rather than letting
    # downstream tasks run against a half-built schema and bury the root cause.
    failed_task = None
    current_task = 'setup'
    try:
        # always starts with SetupTask
        factory.get('setup').run()

        for task_name in tasks_to_run:
            current_task = task_name
            task = factory.get(task_name)
            task.run()
    except Exception as e:
        failed_task = current_task
        error(f"Critical failure in task '{failed_task}': {e}; aborting pipeline")

    # Always run finalizer and close the DB, even after a failure, so temporary
    # state is cleaned up.
    try:
        factory.get('finalize').run()
    finally:
        db.close()

    if failed_task is not None:
        raise SystemExit(f"PALM-GeM aborted: task '{failed_task}' failed.")


if __name__ == "__main__":
    # Read argparse
    arg = ArgumentParser()
    arg.add_argument('-c', '--config', help="Configuration file")
    args = arg.parse_args()

    main(args)