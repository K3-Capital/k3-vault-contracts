# Agent guide

## What this repository does

K3 vault contracts: a Foundry/Solidity implementation of a fully asynchronous ERC-7540/ERC-4626 vault around a manually managed smart account (often a Safe). The wrapper is also the ERC-20 share token. Strategies, valuation, and fees live outside these contracts; the settlement authority supplies a trusted, post-fee NAV.

Read this guide first, then the relevant source/tests. `ARCHITECTURE.md` is the detailed as-built accounting and trust-model reference; `README.md` is the project overview; `bash/README.md` is the deployment/mining runbook. Check implementation details against source rather than treating documentation snippets as complete storage layouts.

## Repository map

| Path | Responsibility |
| --- | --- |
| `src/SmartAccountWrapper.sol` | Concrete implementation: initialization, owner/roles, pause, smart-account authority, shared reentrancy guard, rescue, ERC-165 support. |
| `src/EpochStagedERC7540Vault.sol` | Core accounting: requests, epoch state machine, settlement pricing/netting, controller queues, lazy claims, ERC-4626 views. |
| `src/Staging.sol` | Separate custody for pending assets/shares and settled claim assets/shares; only its immutable vault can transfer tokens. |
| `src/IEpochStagedERC7540Vault.sol` | Request/operator/epoch API and events. |
| `src/IEpochSettlementPreview.sol` | ERC-165-advertised exact settlement-output preview capability. |
| `test/` | Foundry unit, compliance, fuzz, invariant, deployment, and callback/reentrancy tests. |
| `script/Deploy.s.sol` | `DeployAll`, `RequestDeposit`, and `RequestRedeem` Foundry entrypoints. |
| `script/utils/AtomicDeployment.sol`, `DeployHelper.sol` | One-shot atomic coordinator and deterministic CREATE3 component deployment. |
| `script/Upgrade.s.sol` | Deploy a fresh implementation and upgrade an existing beacon; no proxy reinitialization. |
| `bash/` | Deployment/upgrade previews and broadcast wrappers, address prediction, explorer verification. |
| `tools/` | Offline wrapper vanity-salt miner: Python orchestration, Rust CPU backend, optional CUDA backend and public-job runner. |
| `deployments/` | Canonical production registry, pinned verification/smoke-test evidence, manifest validator and tests. |
| `lib/` | Third-party forge-std, OpenZeppelin upgradeable (including nested non-upgradeable contracts), and Solady sources. Avoid editing vendored code. |
| `.github/workflows/test.yml` | Authoritative CI checks. |

## Core flow and accounting

1. `requestDeposit(assets, controller, owner)` transfers underlying from the owner into `Staging`, measures the received balance delta, and records the current epoch. It does not mint shares.
2. `requestRedeem(shares, controller, owner)` transfers existing shares into `Staging`. They remain in total supply until settlement.
3. Only `smartAccount()` may call `closeEpoch()`. It freezes the current epoch and immediately opens the next one. Only one closed-but-unsettled epoch may exist; new requests can still enter the open epoch.
4. The smart account calculates NAV excluding staged deposits and existing redemption claim reserves. It pre-transfers any net redemption funding shortfall to the wrapper before `settleEpoch(epochId, navSnapshot)` (normally in the same smart-account transaction batch). Settlement does not pull assets via allowance.
5. Settlement prices both sides using the same pre-settlement NAV/supply, nets staged deposits against redemption funding, reserves redemption assets in `Staging`, burns requested shares, and mints deposit claim shares into `Staging`. All wrapper surplus is forwarded to the smart account.
6. ERC-4626 `deposit`/`mint` claim settled shares; `withdraw`/`redeem` claim settled assets. These are not synchronous entry/exit functions and do not perform a new request. Each call consumes only the controller's oldest claimable epoch on the relevant side, never multiple epochs.

Request IDs are epoch IDs (`uint40`, starting at 1), not per-user/per-request nonces. Repeated requests aggregate per epoch/controller. Separate linked queues track each controller's deposit and redeem epochs; settlement does not iterate all controllers.

`totalAssets()` returns stored active NAV accounting, not a live token balance or a valuation of strategies. After settlement: `activeAssets = navSnapshot - redeemAssets + totalDepositAssets`. `redeemClaimReserves()` tracks unclaimed redemption assets held in `Staging`; `assetSurplus()` is the wrapper's underlying balance, not the staging balance.

Settlement uses offset-zero virtual accounting (one virtual asset and one virtual share), with floor rounding:

- Deposit shares: `floor(depositAssets * (supplySnapshot + 1) / (navSnapshot + 1))`.
- Redemption assets: `floor(redeemShares * (navSnapshot + 1) / (supplySnapshot + 1))`.

Use `previewSettlement` as the authoritative implementation of this math, including maximum-uint overflow handling and NAV validation. Ordinary `previewDeposit`, `previewMint`, `previewWithdraw`, and `previewRedeem` revert with `SA__AsyncOnly`; `max*` views expose the oldest claimable epoch's remaining amounts, including while paused.

## Security and compatibility rules to preserve

- Distinguish asset/share `owner`, request/claim `controller`, transaction caller, and output `receiver`. `setOperator` approvals are controller-scoped, not transitive.
- A caller other than the owner cannot route a request to a different controller. Deposit requests require the owner's operator approval; redeem requests accept owner-operator approval or ERC-20 share allowance. An owner routing to a different controller must be approved by that controller. Claims require controller/operator authorization before choosing any receiver. See `ERC7540Compliance.t.sol` for regression coverage.
- Pause blocks new requests only. Closing, settlement, claims, and claimable `max*` views remain available. Owner or `PAUSER_ROLE` can pause; only owner can unpause. The current owner is the effective `DEFAULT_ADMIN_ROLE` authority.
- Underlying rescue and smart-account rotation are blocked while an epoch is frozen. Staged underlying and vault shares cannot be rescued; unrelated staged tokens can. Do not weaken reserve protection.
- The concrete wrapper shares one upgradeable reentrancy guard across `requestDeposit`, `settleEpoch`, `withdraw`, and `redeem`. Preserve cross-function protection around external underlying-token calls.
- Floor-rounding residuals go to the final claimant of each epoch/side so funds do not remain stranded. Full-input zero-output dust claims can consume their input and advance queues; partial dust claims remain queued. Exact-output `mint`/`withdraw` reject partial claims whose ceil rounding consumes all remaining input.
- Virtual accounting is not a guarantee against economically unsafe NAV or zero-share deposit epochs. Operators must maintain real-supply floors, reconcile custody inflows/NAV changes, and surface zero-share `previewSettlement` outputs. Underlying assets are assumed standard, non-rebasing, and non-fee-on-transfer.
- Storage is ERC-7201 namespaced. Preserve existing field order/types, namespace strings (including the historical `zyfai.storage.*` names), and slot constants across upgrades. Implementations disable initializers; proxies initialize once and create their own `Staging`.
- Upgrades use an OpenZeppelin `UpgradeableBeacon`/`BeaconProxy`, not UUPS. Beacon-owner upgrades affect its proxies. Owner and settlement authority are high-trust roles, not necessarily Safes/multisigs. The wrapper does not implement ERC-1271.
- No cancellation or normal emergency-settlement entrypoint exists. Major accounting/control-flow changes require a fresh security review/audit before production use.

## Development and verification

Run commands from the repository root. Tooling: recent Foundry (`forge`, `cast`; `anvil` for local deployment work), Python 3.9+, and stable Rust/Cargo for miner tests. CUDA/NVIDIA tooling is optional. Python tooling uses the standard library; there is no root npm application or Python dependency installation step.

`foundry.toml` pins Solidity **0.8.30**, EVM **osaka**, optimizer enabled with **200 runs**. Use a Foundry version supporting those settings; CI installs nightly. Do not change compiler/EVM settings merely to accommodate an old local executable: this changes bytecode, deployment predictions, and verification provenance. Imports use `remappings.txt` for OpenZeppelin and Foundry's library resolution for forge-std/Solady. `.gitmodules` documents upstream dependencies; on a checkout missing dependency contents, initialize recursive submodules.

Canonical CI-equivalent checks:

```sh
forge build
cargo build --release --locked --manifest-path tools/salt-miner/Cargo.toml
python3 -m unittest tools.test_mine_salt tools.test_mining_backend tools.test_salt_boundaries -v
python3 -m unittest deployments/test_validate.py
python3 deployments/validate.py
forge fmt --check
forge build --sizes
forge test -vvv
```

Use `forge fmt` to format intentional Solidity edits; avoid unrelated formatting churn. For focused work, run `forge test --match-path test/ERC7540Compliance.t.sol -vvv` or the corresponding test file, then broader relevant checks. Local core tests use mocks/proxies rather than requiring production RPC credentials. Miner integration tests require compiled Foundry artifacts and the Rust release backend; hardware CUDA tests are separate and are not part of the default CI job.

Test routing:

- `EpochStagedERC7540.t.sol`: state machine, net funding, queues, claims, dust, extremes, donation behavior, rescue/reserves.
- `ERC7540Compliance.t.sol`: authorization routing, allowances/operators, previews, ERC-7575 compatibility.
- `SmartAccountWrapper.t.sol`: initialization, ownership/role changes, pause, interface support.
- `ReentrancyHardening.t.sol`: nested balance-delta and cross-function callbacks, existing proxy guard compatibility.
- `EpochStagedERC7540Fuzz.t.sol`: pricing/rounding and claim conservation.
- `EpochStagedERC7540Invariant.t.sol`: deposit-only supply conservation and pending-versus-claimable separation; do not assume it covers every redemption invariant.
- `AtomicDeployment.t.sol`: atomic CREATE3 deployment and complete rollback on invalid initialization.
- `tools/test_*.py`: independent Foundry prediction vectors, configuration validation, backend fallback/verification, salt boundaries.

## Deployment, mining, and evidence safety

Never broadcast, upgrade, unlock wallets, or submit explorer verification unless explicitly requested. `bash/deploy.sh` and `bash/upgrade.sh` default to dry-run; `bash/predict.sh` is read-only; `bash/verify.sh` submits explorer verification. Consult the runbook before invoking them. Do not read/print real `.env` files or credentials during routine code work; use public fixtures when testing. Use encrypted cast keystores, never plaintext private keys.

Deployment uses CREATE2 for `AtomicDeployment`, whose constructor completes CREATE3 implementation/beacon/proxy deployment and proxy initialization (including `Staging`) in one transaction. Preserve this atomicity. Component salts are derived from the base salt plus `implementation`, `beacon`, or `wrapper`; coordinator derivation also depends on constructor parameters and compiled bytecode.

`tools/mine_salt.py` targets the user-facing wrapper address, not the beacon. Mining is offline, reads public configuration without sourcing shell code, and does not modify `.env`. Auto mode selects usable CUDA or falls back to CPU; every GPU winner must be independently verified by Rust CPU. Keep Python, Rust, CUDA, and Solidity deployment formulas aligned, and retain independent `cast`/real-script reference tests. A change to initialization parameters, build profile/bytecode, or CREATE2 factory invalidates prior predictions. See `bash/README.md` for prerequisite caching, public GPU jobs, resume limits, and final dry-run checks.

Use `deployments/<chain-id>/<wrapper-address>/` for canonical integration addresses and evidence; do not copy historical addresses or assert current live state from a recorded snapshot. The registry records Ethereum and Arc deployments with different activation/smoke-test status. Pending activation is not an on-chain pause/deposit gate. Append upgrade evidence under `upgrades/`; preserve original provenance and immutable timestamped broadcasts. Never commit mutable `run-latest.json`, local/dry-run broadcasts, RPC URLs, API keys, or signer/keystore details. Manifest validation checks local records, not live chain state.

## Change discipline

Keep changes scoped, preserve existing SPDX headers, and respect mixed BUSL-1.1/MIT licensing (`NOTICE.md` and license files). Add regression coverage for changed accounting/authorization behavior and keep `ARCHITECTURE.md`, relevant runbooks, and this guide aligned with intentional design changes. Do not edit generated `out/`, `cache/`, or miner `target/` artifacts or vendor sources as a shortcut. Report the checks actually run and any tooling/hardware blockers; passing local tests is not an audit or proof of production readiness.
