from __future__ import annotations

# Kept as a compatibility entry point. Dataset construction is now the broader
# operation because it includes fixed-FPS windowing, target selection, splits,
# and reproducibility metadata.
from build_dataset import main


if __name__ == "__main__":
    main()
