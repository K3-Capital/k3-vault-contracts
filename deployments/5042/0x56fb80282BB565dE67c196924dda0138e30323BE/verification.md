# Arc mainnet — K3 cirBTC Vault deployment verification

## Verdict and scope

Deployment wiring verified with operational caveats. The deployment transaction succeeded, all five application runtime bytecodes and all three CREATE3 deployer runtimes match source commit `3a78d05b3481a09fbd696b7a0a93474f9887cfc8`, and the proxy wiring, initialization and permission boundaries match the intended configuration. The addresses recorded by the operator in `.env` agree with the live coordinator, implementation, beacon and wrapper addresses. No `.env` values were changed during verification.

Registry status: `deployed-pending-activation`. This is an operational label, not an on-chain gate: the vault is **unpaused**. The owner and settlement authority have empty code, nonce zero and zero native USDC at the snapshot. No funded mainnet deposit/redeem smoke test has been performed. Arc Blockscout source verification is incomplete: the implementation, wrapper proxy and Staging are fully verified, the beacon is partially verified, and the coordinator is not verified. This report does not authorize deposits or replace an independent security audit.

Verification used only read-only RPC and `eth_call`; no transactions were signed or broadcast by the verifier. `eth_call` with an explicit sender proves the contract's permission checks, not control of that sender's key or its ability to submit transactions.

## Deployment identity

- Network: Arc mainnet, chain ID `5042`; gas token: native USDC (RPC balance/fee units use 18 decimals).
- Stable integration address: `0x56fb80282BB565dE67c196924dda0138e30323BE`.
- Vault: `K3 cirBTC Vault` / `k3cirBTC`; asset/share decimals: `8`.
- Underlying asset: user-specified [`0x171A4217b86A807A64eB94757Db6849fb4bDbAA0`](https://explorer.arc.io/token/0x171A4217b86A807A64eB94757Db6849fb4bDbAA0); on-chain metadata reports `Circle Wrapped Bitcoin` / `cirBTC` and 8 decimals. This is an exact address/metadata check, not independent attestation of the issuer.
- Owner and beacon upgrade authority: `0x349bB895dB64f74AB9788693a16Ee03776195504`.
- Settlement authority: `0xf55bFE6C93FefDC3b0F0BD6b05BF7F85e60e5ac1`.
- Deployer: `0x43F4600D98Ae531D7e5F1f8FF68ef97779d31641`.
- Source: [3a78d05b3481a09fbd696b7a0a93474f9887cfc8](https://github.com/K3-Capital/erc7540-wrapper/commit/3a78d05b3481a09fbd696b7a0a93474f9887cfc8). Solidity sources, deployment scripts, vendored libraries and Foundry configuration had no tracked modifications relative to that commit.
- Solidity `0.8.30+commit.73712a01`, EVM `osaka`, optimizer enabled with 200 runs; via-IR disabled, IPFS bytecode metadata and CBOR enabled, literal-content mode disabled. Exact settings and remappings are in [`deployment.json`](deployment.json).
- Reproduction toolchain: Foundry `1.7.1`, commit `4072e48705af9d93e3c0f6e29e93b5e9a40caed8`.

| Component | Address |
| --- | --- |
| AtomicDeployment (coordinator) | [`0x90E1cac2D985E9A961f043b9682EcCe72E86f8F1`](https://explorer.arc.io/address/0x90E1cac2D985E9A961f043b9682EcCe72E86f8F1) |
| SmartAccountWrapper (implementation) | [`0xBF67E0CC43285FF4392bC37b6717f522E4c8e824`](https://explorer.arc.io/address/0xBF67E0CC43285FF4392bC37b6717f522E4c8e824) |
| UpgradeableBeacon (beacon) | [`0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA`](https://explorer.arc.io/address/0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA) |
| BeaconProxy (wrapperProxy) | [`0x56fb80282BB565dE67c196924dda0138e30323BE`](https://explorer.arc.io/address/0x56fb80282BB565dE67c196924dda0138e30323BE) |
| Staging (staging) | [`0x778ef6d801672009bCd878f69055f56907fa2217`](https://explorer.arc.io/address/0x778ef6d801672009bCd878f69055f56907fa2217) |

## Successful atomic deployment

[`0x3eddb609c2efa695fd003bf8e1ad0f2146c1b3cc2a43e9ecfc336a1bf47aae49`](https://explorer.arc.io/tx/0x3eddb609c2efa695fd003bf8e1ad0f2146c1b3cc2a43e9ecfc336a1bf47aae49)

- Receipt status: `1`.
- Block: `22493034`; transaction index: `2`; timestamp: `2026-09-24T09:01:00Z`.
- Block hash: `0xedd2e43ad685c3fc39ab14e58a51cbbd69c28e47c74c55fddb3109c89c3b91dc`.
- Sender nonce: `0`; transaction value: `0`.
- Transaction target: canonical CREATE2 deployer `0x4e59b44847b379578588920cA78FbF26c0B4956C`.
- Gas used: `5205010`; effective gas price: `21000000000` native base units; receipt-derived cost: `0.10930521` USDC.

One transaction created the `AtomicDeployment` coordinator and completed its internal CREATE3 deployment sequence. The implementation, beacon, initialized wrapper proxy and Staging contract were created atomically. This is not the legacy six-transaction deployment flow.

The timestamped Foundry evidence is [`broadcast/Deploy.s.sol/5042/run-1790240460311.json`](../../../broadcast/Deploy.s.sol/5042/run-1790240460311.json). SHA-256: `681da3eb0c64cb0b1c9eceb5253ca5f01c95f67fdf044cb55aba07aba5b8cb36`. Its transaction hash, sender, nonce, destination, value, chain ID and exact calldata match the live transaction. Receipt block/hash/index/status/gas/logs also match. The coordinator creation payload was reconstructed from local creation bytecode and original constructor parameters. No hash-to-payload misassociation was found. The raw artifact was not edited; `run-latest.json` is not the canonical evidence.

The atomic sequence also created the three Solady CREATE3 deployer proxies recorded by the raw artifact. The manifest retains the established `ephemeralDeployers` field name, but these proxies remain on-chain with the expected 8-byte runtime `0x363d3d37363d34f0`, runtime hash `0x0b130a5cdfe5920e22336512f736f182f31e18977d284dba00dcd14b698071a3`, and nonce `2` at the verification snapshot.

| CREATE3 target | Derived salt | Deployer proxy |
| --- | --- | --- |
| implementation | `0xd01dfd2dffb3299755a11109df0ba6f394f5dc5bacded86cab0fc8a6ca4b78dd` | [`0x1cD94c37848e3E671b60dbf75EcC647Cf5A31A96`](https://explorer.arc.io/address/0x1cD94c37848e3E671b60dbf75EcC647Cf5A31A96) |
| beacon | `0x4ab251a39ee88917439fba82aab90760721331f63f811cd3472ef169cec39a5d` | [`0x98f16a786f07Df6bCB85691647A798065565e140`](https://explorer.arc.io/address/0x98f16a786f07Df6bCB85691647A798065565e140) |
| wrapper | `0x8212c2aec118628f64e22f9f53b1ffe7fe9075543b1f25192fcfb88099399be4` | [`0x0273903C4149BCb18a1719c75070628Aa0501776`](https://explorer.arc.io/address/0x0273903C4149BCb18a1719c75070628Aa0501776) |

The spent helpers are permissionless and can still create children at later nonces, as covered by `AtomicDeployment.t.sol`; they cannot recreate or modify the nonce-one implementation, beacon or wrapper. They have no vault role or authority.

## Arc Blockscout source status

A read-only Arc Blockscout API check at `2026-09-24T10:03:03Z` reported full source verification for SmartAccountWrapper, BeaconProxy and Staging, partial verification for UpgradeableBeacon, and no source verification for AtomicDeployment. The explorer-returned runtime bytecode for each listed application address was independently hashed and matched the runtime hash recorded below. See [`explorer-status.json`](explorer-status.json), SHA-256 `a5477768c871d76c9910ac12cf2f42cdbd24b2def3645e9c0df8a69fed349c75`.

Explorer source status is separate from the exact local bytecode provenance checks in this report. The deployment remains source-verification-incomplete until the coordinator is verified and the beacon is fully verified.

## Pinned state and bytecode

Snapshot: block `22494955` (`2026-09-24T09:17:15Z`), hash `0x10447359d023eb72d9e783f3a0478741b26a34ec91b0e20a794bc034d72a1df6`. Critical views and storage were independently rechecked unchanged at block `22494963` (`2026-09-24T09:17:19Z`), hash `0x577de1398c6fc1a7e252a0bde01308196c279d33c525b8ab370610f324bd9c5e`.

| Contract | Runtime bytes | Runtime Keccak-256 |
| --- | ---: | --- |
| AtomicDeployment | 258 | `0x38a2a18b25f452c3fef2c49c04723761fdc318d7bc1b2fff65412ced5e06db4f` |
| SmartAccountWrapper | 19167 | `0xad4777be5d6dcef322b94b7d0d30a1cbf5e8f44f98b011cf7ba4490afb836cd5` |
| UpgradeableBeacon | 644 | `0x0ce4415c191fe5f2c89e67fd04fc646aa9b61958a01026bf58029708b8bd2a51` |
| BeaconProxy | 283 | `0xe66a3b02bbd22f6336cf260ad79da57ae221b0a952f8847af8e77fd311dc7a16` |
| Staging | 577 | `0x88a6671cd7693bf05005fa16a7620f61ae40125137311e1b556a6760b347e071` |
| implementation CREATE3 deployer | 8 | `0x0b130a5cdfe5920e22336512f736f182f31e18977d284dba00dcd14b698071a3` |
| beacon CREATE3 deployer | 8 | `0x0b130a5cdfe5920e22336512f736f182f31e18977d284dba00dcd14b698071a3` |
| wrapper CREATE3 deployer | 8 | `0x0b130a5cdfe5920e22336512f736f182f31e18977d284dba00dcd14b698071a3` |

All five application runtimes and all three CREATE3 deployer runtimes matched exactly. Immutable references were substituted before comparison: coordinator implementation/beacon/wrapper, proxy beacon, and Staging vault. The implementation, beacon and CREATE3 deployers have no immutable substitutions. Named coordinator getters independently matched their expected roles.

- ERC-1967 beacon slot points to `0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA`; implementation and admin slots are zero, as expected for this beacon architecture.
- OpenZeppelin v5 BeaconProxy's immutable beacon also matches `0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA`; the slot alone was not used as proof of delegation.
- Beacon `implementation()` equals `0xBF67E0CC43285FF4392bC37b6717f522E4c8e824`; beacon `owner()` equals the configured owner.
- Wrapper `asset()`, `smartAccount()`, `owner()`, `name()`, `symbol()` and decimals match the requested configuration; `share()` equals the wrapper itself.
- Staging `vault()` equals the wrapper. Pending owner is zero; only the owner has the default admin role among the checked owner/settler accounts.
- Proxy initialization version is `1`; the standalone implementation initialization version is the disabled value `uint64.max`. Both reinitializing the proxy and initializing the implementation reverted with `InvalidInitialization()`.
- Current epoch `1`, frozen epoch `0`, total supply `0`, total assets `0`, redeem reserves `0`, asset surplus `0`.
- Wrapper/Staging cirBTC balances and Staging share balance are all zero. The vault and underlying token are unpaused.

## Read-only authorization checks

All 16 checks passed at the pinned snapshot. Each call was isolated: a simulated `closeEpoch()` did not persist state for a subsequent call.

| Check | Expected result | Outcome |
| --- | --- | --- |
| `settler_can_close` | success | Passed |
| `owner_cannot_close` | `SA__NotSmartAccount()` | Passed |
| `deployer_cannot_close` | `SA__NotSmartAccount()` | Passed |
| `settler_reaches_settlement_state_guard` | `SA__NoFrozenEpoch()` | Passed |
| `owner_cannot_settle` | `SA__NotSmartAccount()` | Passed |
| `owner_can_pause` | success | Passed |
| `settler_cannot_pause` | `AccessControlUnauthorizedAccount(address,bytes32)` | Passed |
| `deployer_cannot_pause` | `AccessControlUnauthorizedAccount(address,bytes32)` | Passed |
| `owner_can_set_smart_account` | success | Passed |
| `settler_cannot_set_smart_account` | `OwnableUnauthorizedAccount(address)` | Passed |
| `beacon_owner_can_upgrade_to_current` | success | Passed |
| `settler_cannot_upgrade` | `OwnableUnauthorizedAccount(address)` | Passed |
| `deployer_cannot_upgrade` | `OwnableUnauthorizedAccount(address)` | Passed |
| `proxy_cannot_reinitialize` | `InvalidInitialization()` | Passed |
| `implementation_cannot_initialize` | `InvalidInitialization()` | Passed |
| `outsider_cannot_move_staged_assets` | `ST__NotVault()` | Passed |

The positive close simulation returned closed/next epoch IDs `(1, 2)`. The authorized settlement probe reaches `SA__NoFrozenEpoch()`, proving the authorization gate was passed; it does **not** demonstrate successful settlement, NAV correctness or redemption liquidity. The upgrade probe only simulated upgrading the beacon to its current implementation; no upgrade occurred.

## Operational caveats and activation requirements

At block `22494955`, both privileged addresses have code `0x`, nonce `0`, and native balance `0`. The manifest labels them `EOA` based on empty runtime code; this does not establish possession of their keys or rule out an intended counterfactual account. Neither currently has an on-chain Safe, delegation implementation or timelock.

1. Confirm actual signing control of the owner and settlement authority. If a Safe or delegated smart account was intended, deploy/configure and verify that execution path before activation. Empty code is compatible with an intentional EOA, not evidence of a deployed smart account.
2. Arrange native USDC gas funding or a validated sponsorship path for each required actor. Deployer funds do not make the owner/settlement authority operational.
3. The owner controls wrapper administration and beacon upgrades without an observed on-chain multisig/timelock. The settlement authority controls epoch progression and the reported NAV, and directly receives custody assets during settlement. Confirm these trust assumptions explicitly.
4. Complete matching-source publication on Arc Blockscout for AtomicDeployment and obtain full verification for UpgradeableBeacon. SmartAccountWrapper, BeaconProxy and Staging are fully verified. This is separate from the exact local runtime verification above; an explorer failure is not a reason to redeploy.
5. Approve cirBTC-specific minimum bootstrap capital **and an ongoing minimum real-share supply floor**, with a policy preventing seed redemption below that floor; initialization or a one-time seed alone is insufficient. Approve custody/NAV reconciliation, warning and hard-stop thresholds, redemption liquidity and production security review. Integrators must use the authoritative `previewSettlement` output and escalate material zero-share previews under an approved dust policy. These operating requirements in [ARCHITECTURE.md](../../../ARCHITECTURE.md#donation-and-nav-inflation-security-assumptions) are not established by this verification and are not enforced as launch gates on-chain. With the vault already unpaused, pending-activation status by itself does not prevent users requesting deposits. Any decision to pause or otherwise restrict launch needs a separately authorized owner transaction.
6. Under a separately approved funded plan, execute a deposit request, close/settle, share claim, redemption request, close/settle and asset claim through the real signing path. Record every receipt and a coherent post-smoke snapshot before marking the deployment active. No smoke evidence file is present because no such test was performed.

## Local validation and future records

A fresh local test execution returned **91 passed, zero failed, zero skipped**. `forge fmt --check` and `forge build --sizes` passed; the implementation is within the deployment size limit. Local tests do not exercise the live owner's signing setup or constitute a funded mainnet smoke test.

From the repository root, validate the registry with:

```bash
python3 -m unittest deployments/test_validate.py
python3 deployments/validate.py
```

For ongoing read-only checks, load your local RPC configuration without printing credentials, then:

```bash
cast chain-id --rpc-url "$RPC_URL"
cast receipt 0x3eddb609c2efa695fd003bf8e1ad0f2146c1b3cc2a43e9ecfc336a1bf47aae49 --rpc-url "$RPC_URL"
cast call 0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA 'implementation()(address)' --rpc-url "$RPC_URL"
cast call 0xc77Fb640FD7D6B056Fa30C74cB9eF65B3636C4fA 'owner()(address)' --rpc-url "$RPC_URL"
cast call 0x56fb80282BB565dE67c196924dda0138e30323BE 'owner()(address)' --rpc-url "$RPC_URL"
cast call 0x56fb80282BB565dE67c196924dda0138e30323BE 'smartAccount()(address)' --rpc-url "$RPC_URL"
cast call 0x56fb80282BB565dE67c196924dda0138e30323BE 'asset()(address)' --rpc-url "$RPC_URL"
cast call 0x56fb80282BB565dE67c196924dda0138e30323BE 'paused()(bool)' --rpc-url "$RPC_URL"
```

Pin related production monitoring reads to one block. Preserve the original deployment facts; add dated activation evidence and append-only `upgrades/` records for future beacon changes. See the [registry policy](../../README.md).
