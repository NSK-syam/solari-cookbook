#!/usr/bin/env python3
"""Exercise the Vercel entrypoint, SPA shell, liveness, and readiness locally."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "api" / "index.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("closing_rescue_vercel", ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Vercel entrypoint could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with TestClient(module.app) as client:
        root = client.get("/")
        health = client.get("/api/v1/health")
        ready = client.get("/api/v1/ready")

    assert root.status_code == 200 and "text/html" in root.headers["content-type"]
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert ready.status_code == 200 and ready.json()["database"] == "ok"
    print("Deployment smoke passed: SPA, liveness, and database readiness are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
