#!/usr/bin/env python3
"""Run a public mining job on a precompiled CUDA backend (no Foundry/keys/RPC).

Copy this file, the compiled backend, and the exported JSON job to the GPU
machine and run locally. Use mine_salt.py --verify-result for CPU checking.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

PARAMETERS = {"OWNER", "SMART_ACCOUNT", "UNDERLYING_TOKEN", "VAULT_NAME", "VAULT_SYMBOL"}


def validate_job(job):
    if not isinstance(job, dict) or set(job) != {"schemaVersion", "input", "parameters"} or job["schemaVersion"] != 1:
        raise ValueError("unsupported public mining job schema")
    params = job["parameters"]
    if not isinstance(params, dict) or set(params) != PARAMETERS or not all(isinstance(v, str) for v in params.values()):
        raise ValueError("job must contain only public initialization parameters")
    payload = job["input"]
    if not isinstance(payload, str) or len(payload) > 2_000_000:
        raise ValueError("invalid or oversized mining input")
    lines = payload.splitlines()
    if len(lines) != 7:
        raise ValueError("expected seven mining input fields")
    factory, before, after, start, prefix, count, target = lines
    if not re.fullmatch(r"[0-9a-fA-F]{40}", factory) or not re.fullmatch(r"[0-9a-fA-F]{64}", start):
        raise ValueError("invalid factory or salt")
    for text in [before, after]:
        if len(text) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", text):
            raise ValueError("invalid initcode hex")
    if not before or not re.fullmatch(r"[0-9a-fA-F]{1,40}", prefix) or target != "wrapper":
        raise ValueError("invalid wrapper target or prefix")
    if not re.fullmatch(r"[0-9]{1,20}", count) or not 0 < int(count) < 2**64:
        raise ValueError("invalid search limit")
    if int(start, 16) + int(count) > 2**256:
        raise ValueError("search range overflows bytes32")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--binary", type=Path, required=True, help="precompiled CUDA miner path")
    args = parser.parse_args()
    try:
        job = json.loads(args.job.read_text())
        lines = validate_job(job)
        for key in sorted(PARAMETERS):
            print(f"  {key}={job['parameters'][key]}", file=sys.stderr)
        # Direct exec, not a shell; only the public protocol is sent to the backend.
        run = subprocess.run([str(args.binary.resolve())], input=job["input"],
                             text=True, stdout=subprocess.PIPE)
        if run.returncode:
            return run.returncode
        result = json.loads(run.stdout)
        if not isinstance(result, dict):
            raise ValueError("backend returned an invalid result")
        result.update(parameters=job["parameters"], prefix=lines[4].lower(),
                      searchStart="0x" + lines[3].lower(), searchLimit=int(lines[5]),
                      jobHash=hashlib.sha256(json.dumps(job, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                      verification="pending-local-cpu-verification")
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
