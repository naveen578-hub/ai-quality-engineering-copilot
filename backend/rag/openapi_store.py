"""
Holds parsed OpenAPI specs for the lifetime of the process.

In-memory by design: specs are re-uploadable in seconds and there's no
retrieval/ranking need here (unlike the requirement chunks in rag/store.py),
so a persistent vector store would be overkill. Restarting the backend
means re-uploading specs — documented as a known limitation.
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from backend.rag.openapi_parser import EndpointSpec

_specs: Dict[str, Dict] = {}


def add_spec(filename: str, endpoints: List[EndpointSpec]) -> str:
    spec_id = f"spec-{uuid.uuid4().hex[:10]}"
    _specs[spec_id] = {"spec_id": spec_id, "filename": filename, "endpoints": endpoints}
    return spec_id


def get_spec(spec_id: str) -> Optional[Dict]:
    return _specs.get(spec_id)


def list_specs() -> List[Dict]:
    return [
        {"spec_id": s["spec_id"], "filename": s["filename"], "endpoint_count": len(s["endpoints"])}
        for s in _specs.values()
    ]


def reset() -> None:
    _specs.clear()
