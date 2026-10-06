from __future__ import annotations

import pytest

from tf.datasets import DatasetSnapshotError, load_market_snapshot, prepare_market_snapshot
from tf.marketdata import synthetic_market


def _write_market_csv(path, n: int = 220) -> None:
    data = synthetic_market(n=n, seed=17)
    rows = ["ts,open,high,low,close"]
    rows.extend(
        f"{int(data.ts[i])},{data.open[i]},{data.high[i]},{data.low[i]},{data.close[i]}"
        for i in range(n)
    )
    path.write_text("\n".join(rows))


def test_snapshot_is_immutable_and_hash_verified(tmp_path):
    source = tmp_path / "source.csv"
    dataset_dir = tmp_path / "snapshots"
    _write_market_csv(source)

    snapshot, digest = prepare_market_snapshot(source, dataset_dir)
    loaded = load_market_snapshot(snapshot, digest, dataset_dir)
    assert len(loaded) == 220
    assert snapshot.name == f"{digest}.csv"

    snapshot.write_text("corrupted")
    with pytest.raises(DatasetSnapshotError, match="hash de dataset"):
        load_market_snapshot(snapshot, digest, dataset_dir)


def test_snapshot_loader_rejects_paths_outside_dataset_root(tmp_path):
    outside = tmp_path / "outside.csv"
    _write_market_csv(outside)
    _, digest = prepare_market_snapshot(outside, tmp_path / "snapshots")

    with pytest.raises(DatasetSnapshotError, match="fuera de TF_DATASET_DIR"):
        load_market_snapshot(outside, digest, tmp_path / "snapshots")
