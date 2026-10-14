#!/usr/bin/env python3
"""Host-local CUDA checks using public vectors or local Foundry reference tools."""
import argparse
import json
import os
import subprocess
import unittest
from pathlib import Path
import sys

BINARY = Path(os.environ.get('K3_CUDA_MINER', './k3-salt-cuda')).resolve()

class CudaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global ROOT
        ROOT = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(ROOT))
        from tools.mine_salt import prepare
        global reference_addresses, keccak
        from tools.test_mine_salt import reference_addresses, keccak
        cls.params = dict(OWNER='0x'+'11'*20, SMART_ACCOUNT='0x'+'22'*20,
                          UNDERLYING_TOKEN='0x'+'44'*20, VAULT_NAME='Test Vault', VAULT_SYMBOL='TEST')
        cls.factory, cls.before, cls.after = prepare(dict(cls.params, DEPLOY_SALT='0x'+(1).to_bytes(32,'big').hex()))

    def invoke(self, start=1, prefix='', limit=1, override=None, before=None, after=None):
        lines = [self.factory[2:], (self.before if before is None else before).hex(),
                 (self.after if after is None else after).hex(), start.to_bytes(32,'big').hex(), prefix, str(limit), 'wrapper']
        if override:
            for i,v in override.items(): lines[i]=v
        return subprocess.run([str(BINARY)], input='\n'.join(lines)+'\n', text=True, capture_output=True)

    def test_predict_matches_independent_foundry(self):
        run = self.invoke()
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result['addresses'], reference_addresses((1).to_bytes(32,'big'), self.params))
        self.assertEqual(result['initcodeHash'], '0x'+keccak(self.before+(1).to_bytes(32,'big')+self.after).hex())
        self.assertEqual(result['attempts'], 1)

    def test_odd_nibble_gpu_and_changed_constructor(self):
        for start in [1, 256, 2**64, 2**256-1]:
            expected = reference_addresses(start.to_bytes(32,'big'), self.params)
            run = self.invoke(start=start, prefix=expected['wrapper'][2:5].upper())
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['addresses'], expected)

    def test_first_match_matches_rust_and_bytes32_carry(self):
        for start in [1, 2**64-3, 2**128-3, 2**248-3]:
            prefix, limit = '3', 1000
            payload = '\n'.join([self.factory[2:], self.before.hex(), self.after.hex(), start.to_bytes(32,'big').hex(), prefix, str(limit), 'wrapper'])+'\n'
            cpu = subprocess.run([str(ROOT/'tools/salt-miner/target/release/k3-salt-miner')], input=payload, text=True, capture_output=True)
            gpu = self.invoke(start, prefix, limit)
            self.assertEqual(cpu.returncode, 0, cpu.stderr)
            self.assertEqual(gpu.returncode, 0, gpu.stderr)
            self.assertEqual(json.loads(gpu.stdout), json.loads(cpu.stdout))

    def test_exhaustion_resume_and_invalid_inputs(self):
        wrong = '0' if reference_addresses((1).to_bytes(32,'big'), self.params)['wrapper'][2]!='0' else '1'
        run = self.invoke(prefix=wrong)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stdout, '')
        self.assertIn('--start 0x'+(2).to_bytes(32,'big').hex(), run.stderr)
        for overrides in [{5:'0'}, {5:'-1'}, {5:str(2**64)}, {0:'xyz'}, {3:'00'}, {4:'g'}, {4:'0'*41}, {6:'beacon'}]:
            run = self.invoke(override=overrides)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertEqual(run.stdout, '')
        run = self.invoke(start=2**256-1, limit=2)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn('salt range', run.stderr)

    def test_terminal_range_exhaustion_has_no_resume_salt(self):
        maximum = 2**256 - 1
        for limit in (1, 2):
            start = maximum - limit + 1
            with self.subTest(limit=limit):
                first_nibbles = {
                    reference_addresses(salt.to_bytes(32, 'big'), self.params)['wrapper'][2]
                    for salt in range(start, maximum + 1)
                }
                wrong = next(nibble for nibble in '0123456789abcdef'
                             if nibble not in first_nibbles)
                run = self.invoke(start=start, prefix=wrong, limit=limit)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertEqual(run.stdout, '')
                self.assertIn(f'No match in {limit} candidates', run.stderr)
                self.assertIn('no resume salt', run.stderr)
                self.assertNotIn('--start', run.stderr)
                self.assertNotIn('Error:', run.stderr)

    def test_keccak_rate_boundaries_on_gpu(self):
        # Prefix cursor positions, salt crossing the rate, multi-block suffix, and empty data.
        for n in [0, 1, 103, 104, 105, 135, 136, 137, 271, 272]:
            before, after = bytes(i%256 for i in range(n)), bytes(i%251 for i in range(280))
            factory = bytes.fromhex(self.factory[2:]); salt=(1).to_bytes(32,'big')
            ih = keccak(before+salt+after)
            coord = keccak(b'\xff'+factory+keccak(salt+b'atomic-deployment')+ih)[12:]
            ph=bytes.fromhex('21c35dbe1b344a2488cf3321d6ce542f8e9f305544ff09e4993a62319a497c1f')
            proxy=keccak(b'\xff'+coord+keccak(salt+b'wrapper')+ph)[12:]
            wrapper=keccak(b'\xd6\x94'+proxy+b'\x01')[12:]
            run=self.invoke(prefix=wrapper.hex(), before=before, after=after)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['initcodeHash'], '0x'+ih.hex())

    def test_bounded_six_nibble_search(self):
        run = self.invoke(prefix='333333', limit=100_000_000)
        self.assertEqual(run.returncode, 0, run.stderr)
        result=json.loads(run.stdout)
        self.assertTrue(result['addresses']['wrapper'].startswith('0x333333'))
        self.assertEqual(int(result['salt'],16), result['attempts'])
        self.assertEqual(result['addresses'], reference_addresses(bytes.fromhex(result['salt'][2:]), self.params))
        print('BENCHMARK '+run.stderr.strip(), flush=True)
        print('WINNER '+json.dumps(result), flush=True)

def run_vectors(path):
    vectors = json.loads(path.read_text())
    if vectors.get('schemaVersion') != 1 or not isinstance(vectors.get('cases'), list) or not vectors['cases']:
        raise ValueError('unsupported CUDA test vector schema')
    for case in vectors['cases']:
        result = subprocess.run([str(BINARY)], input=case['input'], text=True, capture_output=True)
        if result.returncode != case['exitCode']:
            raise AssertionError(f"{case['name']}: exit {result.returncode}; {result.stderr}")
        if 'result' in case and json.loads(result.stdout) != case['result']:
            raise AssertionError(f"{case['name']}: result differs from CPU reference")
        if 'stderrContains' in case and case['stderrContains'] not in result.stderr:
            raise AssertionError(f"{case['name']}: missing expected diagnostic")
        print(f"PASS {case['name']}")
    print(f"{len(vectors['cases'])} CUDA protocol vectors passed")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=BINARY)
    parser.add_argument('--vectors', type=Path, help='public CPU-generated vectors; no Foundry required')
    args, remaining = parser.parse_known_args()
    BINARY = args.binary.resolve()
    if args.vectors:
        run_vectors(args.vectors)
    else:
        unittest.main(argv=[sys.argv[0], *remaining])
