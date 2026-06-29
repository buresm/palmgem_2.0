import time
from argparse import ArgumentParser
from src.config_loader import load_config
from src.logger import setup_logging, progress, debug, error, warning
from src.tasks.factory import TaskFactory
from src.database import Database


def _run_task(factory, name):
    """Run a single task, bracketed by progress logging with elapsed time."""
    progress("---> task '{}' starting", name)
    t0 = time.perf_counter()
    factory.get(name).run()
    progress("<--- task '{}' finished ({:.1f}s)", name, time.perf_counter() - t0)


def main(args=None):
    # 1. Load Config
    config_file = args.config
    cfg = load_config(config_file)

    # 2. Setup Logging
    setup_logging(cfg)
    progress("PALM-GeM starting (config: {})", config_file)

    # 3. Connect to postgres
    debug("connecting to database '{}' on {}:{}",
          cfg.database.database, cfg.database.host, cfg.database.get('port', 5432))
    db = Database(cfg.database._settings, cfg.pg_owner)

    # 4. Identify Tasks — setup and finalize are always run explicitly
    all_tasks = cfg.run_tasks if isinstance(cfg.run_tasks, list) else [cfg.run_tasks]
    tasks_to_run = [t for t in all_tasks if t not in ('setup', 'finalize')]

    progress("workflow tasks (in order): {}", tasks_to_run)

    factory = TaskFactory(cfg, db)

    # Tasks run sequentially and later tasks depend on the schema state left by
    # earlier ones, so a failure is fatal: abort the pipeline rather than letting
    # downstream tasks run against a half-built schema and bury the root cause.
    failed_task = None
    current_task = 'setup'
    run_start = time.perf_counter()
    try:
        # always starts with SetupTask
        _run_task(factory, 'setup')

        for task_name in tasks_to_run:
            current_task = task_name
            _run_task(factory, task_name)
    except Exception as e:
        failed_task = current_task
        error(f"Critical failure in task '{failed_task}': {e}; aborting pipeline")

    # Always run finalizer and close the DB, even after a failure, so temporary
    # state is cleaned up.
    try:
        _run_task(factory, 'finalize')
    finally:
        debug("closing database connection")
        db.close()

    if failed_task is None:
        progress("PALM-GeM completed all tasks ({:.1f}s total)",
                 time.perf_counter() - run_start)
    else:
        raise SystemExit(f"PALM-GeM aborted: task '{failed_task}' failed.")


if __name__ == "__main__":
    # Read argparse
    arg = ArgumentParser()
    arg.add_argument('-c', '--config', help="Configuration file")
    args = arg.parse_args()

    main(args)