"""Shared open-data intelligence platform for IntellCluster.

The package is intentionally source-agnostic: source adapters normalize public
records into common entities, enrichment providers add optional commercial
signals, and vertical products consume the normalized layer.
"""

from .models import EntityRecord, SourceRecord

__all__ = ["EntityRecord", "SourceRecord"]
