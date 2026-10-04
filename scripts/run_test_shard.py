"""Run one deterministic partition of the full pytest collection."""

import argparse

import pytest


class Shard:
    def __init__(self, index: int, count: int) -> None:
        self.index = index
        self.count = count

    def pytest_collection_modifyitems(self, config, items):
        ordered = sorted(items, key=lambda item: item.nodeid)
        selected = ordered[self.index :: self.count]
        selected_ids = {item.nodeid for item in selected}
        deselected = [item for item in ordered if item.nodeid not in selected_ids]
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=int, help="Zero-based shard index")
    parser.add_argument("count", type=int, help="Total number of shards")
    args, pytest_args = parser.parse_known_args()
    if not 0 <= args.index < args.count:
        parser.error("Require 0 <= index < count")
    raise SystemExit(pytest.main(["tests", *pytest_args], plugins=[Shard(args.index, args.count)]))
