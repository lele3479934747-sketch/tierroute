import argparse
import json
import sys

from .backtest import backtest as run_backtest, load_tasks
from . import jobs, receipts
from .router import Router, load_config

COMMANDS = {"route", "plan", "backtest", "stats"}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `tierroute "some task"` still works: no subcommand means route.
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "route")

    p = argparse.ArgumentParser(prog="tierroute", description="Choose a model and effort for a task.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="route one task")
    r.add_argument("task", nargs="?", help="task text; reads stdin if omitted")
    r.add_argument("--kind")
    r.add_argument("--high-stakes", action="store_true")
    r.add_argument("--current-tier", help="tier of the model already holding the conversation")
    r.add_argument("--context-tokens", type=int, default=0)
    r.add_argument("--config")
    r.add_argument("--preset", help="bundled preset, e.g. anthropic")

    j = sub.add_parser("plan", help="resolve the declared routes of a job file")
    j.add_argument("job")
    j.add_argument("--config")
    j.add_argument("--preset", help="bundled preset, e.g. anthropic")

    b = sub.add_parser("backtest", help="estimate cost of routing past tasks vs one tier")
    b.add_argument("tasks", help=".jsonl or .txt, one task per line")
    b.add_argument("--baseline", default="deep")
    b.add_argument("--rows", action="store_true", help="include per-task rows")
    b.add_argument("--config")
    b.add_argument("--preset", help="bundled preset, e.g. anthropic")

    s = sub.add_parser("stats", help="summarise a receipts log")
    s.add_argument("receipts")

    a = p.parse_args(argv)

    if a.cmd == "stats":
        out = receipts.summarise(receipts.read(a.receipts))
    else:
        router = Router(load_config(a.config, preset=a.preset))
        if a.cmd == "route":
            task = a.task if a.task is not None else sys.stdin.read()
            out = router.decide(task, kind=a.kind, high_stakes=a.high_stakes,
                                current_tier=a.current_tier, context_tokens=a.context_tokens).to_dict()
        elif a.cmd == "plan":
            out = jobs.plan_job(jobs.load_job(a.job), router)
        else:
            out = run_backtest(load_tasks(a.tasks), router, baseline=a.baseline)
            if not a.rows:
                out.pop("rows")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
