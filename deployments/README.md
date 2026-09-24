# Deployment registry

This directory is the canonical repository record of production deployments built from this source tree.

Deployments are organized by EVM chain ID and wrapper proxy address:

```text
deployments/<chain-id>/<wrapper-address>/
```

Each deployment directory contains:

- `deployment.json` — machine-readable addresses, source provenance, transaction receipts, compiler settings, and verification evidence;
- `verification.md` — human-readable deployment, proxy, bytecode, configuration, authorization, and smoke-test report; and
- `smoke-test.json` — immutable transaction-by-transaction evidence when a production smoke test has been performed. Pending deployments explicitly record `mainnetSmokeTest.status: not-performed`, a reason, and `documentation.smokeTestEvidence: null`; they must not claim post-smoke state or active status.

When an implementation is upgraded, add append-only records under an `upgrades/` subdirectory.

The exact timestamped Foundry broadcast artifact may also be retained under `broadcast/` as supporting evidence. It is not automatically authoritative: any known generator defect must be recorded in the deployment manifest and verification report. Timestamped artifacts are immutable; mutable `run-latest.json` aliases, local-chain broadcasts, and dry runs are ignored.

## Published deployments

| Chain | Vault | Wrapper proxy | Status | Record |
| --- | --- | --- | --- | --- |
| Ethereum (`1`) | K3 cbBTC Vault (`k3cbBTC`) | [`0x009c02a73706a68e0aE0209235408206E4F53709`](https://etherscan.io/address/0x009c02a73706a68e0ae0209235408206e4f53709) | Active; verified and mainnet smoke-tested | [`deployment.json`](1/0x009c02a73706a68e0aE0209235408206E4F53709/deployment.json) · [`verification.md`](1/0x009c02a73706a68e0aE0209235408206E4F53709/verification.md) |
| Arc (`5042`) | K3 cirBTC Vault (`k3cirBTC`) | [`0x56fb80282BB565dE67c196924dda0138e30323BE`](https://explorer.arc.io/address/0x56fb80282BB565dE67c196924dda0138e30323BE) | Wiring verified; source verification incomplete; pending activation and funded smoke test | [`deployment.json`](5042/0x56fb80282BB565dE67c196924dda0138e30323BE/deployment.json) · [`verification.md`](5042/0x56fb80282BB565dE67c196924dda0138e30323BE/verification.md) |

The Arc vault is unpaused on-chain; pending activation is an operational status, not a deposit gate. Its owner and settlement authority had empty code, nonce zero and no native USDC at the recorded snapshot. Confirm signing control, intended account setup and gas funding before launch.

## Record policy

- Treat the wrapper proxy as the stable integration address.
- Pin every deployment to a full Git commit, compiler configuration, and transaction set.
- Set `source.foundryBroadcast.integrityStatus` to `valid` for a clean artifact, or to `known-hash-to-payload-misassociations` with a non-empty mapping list when that generator defect is present.
- Keep broadcast paths repository-relative, verification/smoke evidence paths deployment-directory-relative, and the registry index path `deployments/`-relative. Absolute paths and `..` traversal are invalid.
- Record all implementation, beacon, proxy, staging, asset, owner, and settlement-authority addresses.
- Describe the observed account type; an empty-code EOA settlement authority does not require invented EIP-7702 delegation data. Empty code does not prove signing control or readiness.
- Record live bytecode hashes and proxy slots at an explicit verification block.
- Never overwrite history after an upgrade. Add an upgrade record and update the deployment status while preserving the original deployment data.
- Do not commit RPC URLs, API keys, keystore names, passwords, private keys, signer lists, or other operational secrets.
- A deployment record proves provenance and wiring at the recorded blocks. It is not a substitute for a security audit, and upgradeable state may change after the latest recorded snapshot.
