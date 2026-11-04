"""Exact splitlines compatibility for the bounded span implementation."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_args


def reference(text, head, tail):
    lines = text.splitlines(keepends=True)
    if len(lines) <= head + tail:
        return text
    body = ''.join(lines[:head])
    if body and not body.endswith(('\n', '\r')):
        body += '\n'
    return body + f'... {len(lines)-head-tail} line(s) omitted ...\n' + ''.join(lines[-tail:] if tail else [])


class TrimMemoryTests(unittest.TestCase):
    def test_all_splitlines_boundaries_and_random_mixtures(self):
        rng = random.Random(20261104)
        samples = ['', 'plain', '\r\n', 'a\r\nb\rc\n', 'x\u2028y\u2029']
        alphabet = 'ab🙂\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'
        samples += [''.join(rng.choice(alphabet) for _ in range(200)) for _ in range(100)]
        for text in samples:
            for head in (0, 1, 3, 300):
                for tail in (0, 1, 3, 300):
                    self.assertEqual(cli_args.trim_output(text, head=head, tail=tail, bounded_memory=True), reference(text, head, tail))
                    if len(text.splitlines()) <= head+tail:
                        self.assertIs(cli_args.trim_output(text, head=head, tail=tail, bounded_memory=True), text)

    def test_large_log(self):
        text = 'line\n' * 100000
        self.assertEqual(cli_args.trim_output(text, head=2, tail=2, bounded_memory=True), reference(text, 2, 2))


if __name__ == '__main__':
    unittest.main()
