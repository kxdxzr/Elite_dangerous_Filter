"""Run from any working directory: python scripts/run_tests.py [test_module ...]."""
from pathlib import Path
import gc
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import tests  # Sets the source/test import paths before discovery.


class MainThreadResult(unittest.TextTestResult):
    def stopTest(self, test):
        super().stopTest(test)
        # Closed Tk fixtures may contain cycles. Collect them on the GUI thread,
        # never incidentally inside a search worker's next Python allocation.
        gc.collect()


if __name__ == '__main__':
    gc.disable()
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(sys.argv[1:]) if len(sys.argv) > 1 else
             loader.discover(str(PROJECT / 'tests'), top_level_dir=str(PROJECT)))
    result = unittest.TextTestRunner(verbosity=2, resultclass=MainThreadResult).run(suite)
    raise SystemExit(not result.wasSuccessful())
