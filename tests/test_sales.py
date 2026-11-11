"""Use a subprocess so other test classes cannot share the same SQLite session."""
import subprocess
import sys
import unittest
from pathlib import Path

class SalesProTests(unittest.TestCase):
    def test_end_to_end(self):
        worker=Path(__file__).with_name('_sales_validation.py')
        run=subprocess.run([sys.executable,str(worker)],capture_output=True,text=True,timeout=45)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
