"""Command-line entry point.

A REST server / UI is intentionally out of scope for this case study.
The CLI prints the same JSON object a REST handler would return.

Commands:
  process            Run the pipeline on one W-9 PDF or image
  evaluate           Score the pipeline against the golden sample set
  generate-samples   Rebuild demo PDFs, supplier master, and labels
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from w9_onboarding.evaluation import evaluate
from w9_onboarding.pipeline import process_document
from w9_onboarding.samples import DATA_DIR, ROOT, generate_fixtures
from w9_onboarding.security import configure_logging


def main(argv: list[str] | None = None) -> int:
    # Install a log filter so raw TINs never leak into console logs.
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="w9-onboard",
        description="Extract a W-9, validate it, and decide new vs update vs review.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- process one document ---
    process_cmd = sub.add_parser("process", help="Run the pipeline on one document")
    process_cmd.add_argument("document", help="Path to a W-9 PDF or image")
    process_cmd.add_argument(
        "--master",
        default=str(DATA_DIR / "supplier_master.csv"),
        help="Tenant supplier master CSV or JSON",
    )
    process_cmd.add_argument("--tenant", default="demo-tenant")
    process_cmd.add_argument("--out", help="Write JSON to this path")
    # Raw TIN is withheld by default; pass this only for a trusted write path.
    process_cmd.add_argument("--include-tin", action="store_true")
    process_cmd.add_argument("--use-llm", action="store_true", help="Enable optional OpenAI refinement")

    # --- score the labeled set ---
    eval_cmd = sub.add_parser("evaluate", help="Score the pipeline against golden samples")
    eval_cmd.add_argument("--data-dir", default=str(DATA_DIR))
    eval_cmd.add_argument("--use-llm", action="store_true")
    eval_cmd.add_argument("--out", help="Write the evaluation report JSON")

    sub.add_parser("generate-samples", help="Regenerate PDFs, master file, and labels")

    args = parser.parse_args(argv)

    if args.command == "generate-samples":
        paths = generate_fixtures(ROOT)
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        return 0

    if args.command == "evaluate":
        report = evaluate(Path(args.data_dir), use_llm=args.use_llm)
        text = json.dumps(report, indent=2)
        print(text)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
        metrics = report["metrics"]
        # Summary line on stderr so JSON on stdout stays machine-parseable.
        print(
            f"\n{metrics['n_cases']} cases  "
            f"decision={metrics['decision_accuracy']:.0%}  "
            f"reason={metrics['reason_accuracy']:.0%}  "
            f"fields={metrics['field_accuracy']:.0%}",
            file=sys.stderr,
        )
        return 0 if metrics["decision_accuracy"] == 1.0 else 1

    # Default path: process one document and print the OnboardingResponse.
    result = process_document(
        args.document,
        args.master,
        tenant_id=args.tenant,
        use_llm=args.use_llm,
    )
    payload = result.to_public_dict(include_tin=args.include_tin)
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
