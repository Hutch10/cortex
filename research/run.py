"""
Cortex -- entry point.

Run the Hub web server:
    python run.py

Generate a client drift report (CLI):
    python run.py --report "Client Name" [options]

Generate the N6424P Hangar Briefing PDF:
    python run.py --briefing
    python run.py --briefing --tenant internal
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))


def start_hub(port: int = 5050, debug: bool = True) -> None:
    from hub.app import app
    print(f"\n  HutchSolves Cortex Hub  http://127.0.0.1:{port}\n")
    app.run(debug=debug, port=port)


def generate_briefing_cli(args) -> None:
    from nerves.aviation.hangar_briefing import HangarBriefingGenerator
    from nerves.aviation.recency_check import RecencyChecker

    # --briefing always targets the internal (aviation) tenant unless overridden
    tenant = args.tenant if args.tenant not in ("", "default") else "internal"
    checker = RecencyChecker()
    status  = checker.check()

    print()
    print(f"  N6424P Recency Check")
    print(f"  --------------------")
    for line in status.summary().splitlines():
        print(f"  {line}")
    print()

    path = HangarBriefingGenerator(tenant_slug=tenant).generate()
    print(f"  Status    : {status.status}")
    print(f"  PDF saved : {path}")
    print()


def generate_report_cli(args) -> None:
    from nerves.consulting.drift_optimizer import DriftOptimizer
    from nerves.consulting.report_gen import ReportGenerator

    signals = {}
    if args.signals:
        for pair in args.signals:
            label, _, val = pair.partition(":")
            if label and val:
                signals[label.strip()] = float(val.strip())

    optimizer = DriftOptimizer(
        client_name    = args.report,
        revenue_trend  = args.revenue,
        process_score  = args.process,
        team_alignment = args.team,
        market_response= args.market,
        custom_signals = signals,
    )
    report = optimizer.analyse()
    path   = ReportGenerator(report, tenant_slug=args.tenant).generate()
    print(f"\n  Drift Score   : {report.drift_score} / 100")
    print(f"  Systems Pulse : {report.systems_pulse}")
    print(f"  PDF saved     : {path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HutchSolves Cortex")
    parser.add_argument("--report",  metavar="CLIENT_NAME",
                        help="Generate a PDF report for the given client name (CLI mode)")
    parser.add_argument("--revenue",  type=float, default=0.0,  help="Revenue trend -1.0 to 1.0")
    parser.add_argument("--process",  type=float, default=50.0, help="Process score 0-100")
    parser.add_argument("--team",     type=float, default=50.0, help="Team alignment 0-100")
    parser.add_argument("--market",   type=float, default=50.0, help="Market response 0-100")
    parser.add_argument("--signals",  nargs="*", metavar="LABEL:VALUE",
                        help="Custom signals e.g. 'NPS:42' 'Speed:78'")
    parser.add_argument("--tenant",   default="default",
                        help="Tenant slug — report saved to outputs/reports/{slug}/")
    parser.add_argument("--port",     type=int, default=5050,   help="Hub server port")
    parser.add_argument("--no-debug", action="store_true",      help="Disable Flask debug mode")
    parser.add_argument("--briefing", action="store_true",
                        help="Generate N6424P Hangar Briefing PDF (CLI mode)")

    args = parser.parse_args()

    if args.briefing:
        generate_briefing_cli(args)
    elif args.report:
        generate_report_cli(args)
    else:
        start_hub(port=args.port, debug=not args.no_debug)
