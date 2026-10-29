"""Train the demand model and save it to models/demand_model.joblib.

The API also trains on first start if the file is missing, so this is mainly
for the deploy build step and for checking the holdout score.

Run from the repo root:  python scripts/train_demand_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import demand  # noqa: E402

if __name__ == "__main__":
    bundle = demand.train()
    print(f"Saved {config.MODEL_PATH.relative_to(config.ROOT)}")
    print("Holdout (most recent 20% of launches):", bundle["metrics"])
