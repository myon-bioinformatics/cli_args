"""Pinned-baseline log trim comparison; input allocated before tracemalloc."""
import json, statistics, subprocess, sys, time, tracemalloc, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cli_args


def main():
    sha = '8663066107021ebe3519593dfc02401494c47751'
    old = types.ModuleType('cli_args_baseline')
    sys.modules[old.__name__] = old
    exec(compile(subprocess.check_output(['git','show',sha+':cli_args.py'],cwd=ROOT),
                 'baseline/cli_args.py','exec'), old.__dict__)
    text = 'example log line with data\n' * 100000
    expected = old.trim_output(text)
    samples = {'baseline': [], 'spans': []}
    functions = {'baseline':old.trim_output, 'spans':lambda text: cli_args.trim_output(text, bounded_memory=True)}
    for i in range(3):
        for name in (list(functions) if i % 2 else list(reversed(functions))):
            tracemalloc.start()
            start = time.perf_counter_ns()
            result = functions[name](text)
            duration = time.perf_counter_ns()-start
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            if result != expected:
                raise SystemExit(f"trim output mismatch: {name}")
            samples[name].append({'ns_under_tracemalloc':duration, 'peak_bytes':peak})
    print(json.dumps({'baseline_sha':sha, 'python':sys.version, 'lines':100000,
        'head':40,'tail':40,'samples':samples,
        'median':{name:{key:statistics.median(row[key] for row in values)
                       for key in values[0]} for name,values in samples.items()}},indent=2))


if __name__ == '__main__':
    main()
