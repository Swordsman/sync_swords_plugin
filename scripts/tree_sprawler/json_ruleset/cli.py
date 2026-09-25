"""CLI entry point: python -m json_ruleset.cli <path> [options]"""

import argparse
import sys
from pathlib import Path
from .core import load_records, build_tree, render


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer a minimal discriminator ruleset from a JSON corpus.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m json_ruleset.cli exports/claude_web/
  python -m json_ruleset.cli conversation.jsonl --max-depth 3
  python -m json_ruleset.cli exports/ --min-coverage 0.2 --max-records 5000
""",
    )
    parser.add_argument("source", type=Path, help="JSON file or directory to analyse")
    parser.add_argument("--max-depth", type=int, default=5, help="max tree depth (default: 5)")
    parser.add_argument("--min-coverage", type=float, default=0.1,
                        help="min fraction of records a field must appear in to be a discriminator candidate (default: 0.1)")
    parser.add_argument("--max-records", type=int, default=50_000,
                        help="max records to load (default: 50000)")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"error: {args.source} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Loading records from {args.source} ...", file=sys.stderr)
    records = load_records(args.source, max_records=args.max_records)

    if not records:
        print("error: no JSON records found", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records):,} records. Building ruleset ...\n", file=sys.stderr)
    tree = build_tree(records, max_depth=args.max_depth, min_coverage=args.min_coverage)
    print(render(tree))


if __name__ == "__main__":
    main()
