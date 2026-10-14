#!/usr/bin/env python3
"""Real CPU miner protocol checks on synthetic public input; no credentials needed."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tools/salt-miner/Cargo.toml'
BINARY = ROOT / 'tools/salt-miner/target/release/k3-salt-miner'
MAX_SALT = 2**256 - 1


class SaltBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            ['cargo', 'build', '--release', '--locked', '--offline',
             '--manifest-path', str(MANIFEST)], cwd=ROOT, check=True,
        )

    def invoke(self, start, prefix='', limit=1):
        payload = '\n'.join([
            '11' * 20, '6000', 'abcd', start.to_bytes(32, 'big').hex(),
            prefix, str(limit), 'wrapper',
        ]) + '\n'
        return subprocess.run([str(BINARY)], input=payload, text=True,
                              capture_output=True, check=False)

    def nonmatching_prefix(self, start, limit):
        # Derive a guaranteed miss from actual success responses, not hash mocks.
        first_nibbles = set()
        for salt in range(start, start + limit):
            result = self.invoke(salt)
            self.assertEqual(result.returncode, 0, result.stderr)
            first_nibbles.add(json.loads(result.stdout)['addresses']['wrapper'][2])
        return next(nibble for nibble in '0123456789abcdef'
                    if nibble not in first_nibbles)

    def test_terminal_range_exhaustion_has_no_resume_salt(self):
        for limit in (1, 2):
            start = MAX_SALT - limit + 1
            with self.subTest(limit=limit):
                result = self.invoke(start, self.nonmatching_prefix(start, limit), limit)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn(f'No match in {limit} candidates', result.stderr)
                self.assertIn('no resume salt', result.stderr)
                self.assertNotIn('--start', result.stderr)
                self.assertNotIn('Error:', result.stderr)

    def test_nonterminal_exhaustion_keeps_resume_salt(self):
        start, limit = MAX_SALT - 2, 2
        result = self.invoke(start, self.nonmatching_prefix(start, limit), limit)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('--start 0x' + MAX_SALT.to_bytes(32, 'big').hex(), result.stderr)
        self.assertNotIn('no resume salt', result.stderr)

    def test_overflow_before_requested_range_completes_is_error(self):
        for start, valid_count in ((MAX_SALT, 1), (MAX_SALT - 1, 2)):
            with self.subTest(start=start):
                result = self.invoke(start, self.nonmatching_prefix(start, valid_count),
                                     valid_count + 1)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('Error: exhausted bytes32 salt range', result.stderr)
                self.assertNotIn('--start', result.stderr)

    def test_terminal_candidate_can_still_match(self):
        result = self.invoke(MAX_SALT)
        self.assertEqual(result.returncode, 0, result.stderr)
        winner = json.loads(result.stdout)
        self.assertEqual(winner['salt'], '0x' + 'ff' * 32)
        self.assertEqual(winner['attempts'], 1)
        exact_match = self.invoke(MAX_SALT, winner['addresses']['wrapper'][2:])
        self.assertEqual(exact_match.returncode, 0, exact_match.stderr)
        self.assertEqual(json.loads(exact_match.stdout), winner)

    def test_zero_limit_remains_invalid(self):
        result = self.invoke(MAX_SALT, limit=0)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('attempt limit must be positive', result.stderr)


if __name__ == '__main__':
    unittest.main()
