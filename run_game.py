from __future__ import annotations

import sys
import multiprocessing as mp

from runtime.standalone import run_standalone_game


if __name__ == '__main__':
    mp.freeze_support()
    scene = sys.argv[1] if len(sys.argv) > 1 else None
    run_standalone_game(scene)
