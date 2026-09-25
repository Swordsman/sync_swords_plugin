"""CLI: python -m tree_sprawler.tree_probe.cli <path> [options]"""

import argparse
import sys
from pathlib import Path
from .core import analyse, render


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer structural vocabulary from a filesystem tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tree_sprawler.tree_probe.cli ~/.kimi/sessions
  python -m tree_sprawler.tree_probe.cli ~/.claude --max-depth 3
  python -m tree_sprawler.tree_probe.cli ~/.kimi/logs --min-support 0.5
""",
    )
    parser.add_argument("root", type=Path, help="directory to analyse")
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--min-support", type=float, default=0.6,
                        help="min fraction of parents sharing a child pattern to count as a unit (default: 0.6)")
    args = parser.parse_args()

    if not args.root.exists() or not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {args.root} ...", file=sys.stderr)
    vocab = analyse(args.root, max_depth=args.max_depth, min_support=args.min_support)
    print(f"Found {vocab.total_entries:,} entries.\n", file=sys.stderr)
    print(render(vocab))


if __name__ == "__main__":
    main()
