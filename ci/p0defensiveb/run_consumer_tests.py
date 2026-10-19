#!/usr/bin/env python3
"""Run only the exact 38 maintained SS/LC consumer IDs with retained raw inputs."""
import argparse
from pathlib import Path
from consumer_contract import run_all
from inventory import parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'peer', 'producer', 'output', 'observer-dir', 'temporary'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument("--remaining-budget-json",type=Path,required=True)
    args = parser.parse_args()
    run_all(args.root, args.peer, args.producer, args.output, args.observer_dir, args.temporary,budget=parse(args.remaining_budget_json.read_bytes()))


if __name__ == '__main__':
    main()
