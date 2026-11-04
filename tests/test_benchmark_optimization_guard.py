"""The benchmark must fail on mismatches even in optimized Python."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OptimizedBenchmarkTests(unittest.TestCase):
    def test_wrong_trim_result_stops_without_success_json(self):
        code = '''
import runpy
ns = runpy.run_path('scripts/benchmark_trim_memory.py')['main'].__globals__
ns['subprocess'].check_output = lambda *a, **kw: b'def trim_output(text): return "reference"'
ns['cli_args'].trim_output = lambda *a, **kw: 'incorrect'
ns['main']()
'''
        result = subprocess.run([sys.executable, '-O', '-S', '-c', code],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('trim output mismatch', result.stderr)
        self.assertEqual(result.stdout, '')
