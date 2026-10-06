"""Snapshots inmutables de datasets para intercambiar referencias por el bus."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from tf.marketdata import MarketData, load_csv


class DatasetSnapshotError(ValueError):
    """Dataset ausente, fuera del almacén aprobado o con hash distinto."""


def prepare_market_snapshot(source: str | Path, dataset_dir: str | Path) -> tuple[Path, str]:
    """Valida y copia un CSV a nombre SHA-256 para que el ciclo sea reproducible."""
    source_path = Path(source).resolve(strict=True)
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    root = Path(dataset_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{digest}.csv"
    if not destination.exists():
        temporary = root / f".{digest}.{os.getpid()}.tmp"
        try:
            temporary.write_bytes(raw)
            load_csv(temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    # Verifica también la copia previa, por corrupción o colisión del almacenamiento.
    load_market_snapshot(destination, digest, root)
    return destination, digest


def load_market_snapshot(
    uri: str | Path,
    expected_sha256: str,
    dataset_dir: str | Path,
) -> MarketData:
    """Carga solo snapshots bajo la raíz permitida y con contenido inmutable."""
    root = Path(dataset_dir).resolve(strict=True)
    path = Path(uri).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DatasetSnapshotError(f"dataset fuera de TF_DATASET_DIR: {path}") from exc
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise DatasetSnapshotError(
            f"hash de dataset no coincide: esperado {expected_sha256}, obtenido {actual}"
        )
    return load_csv(path)
