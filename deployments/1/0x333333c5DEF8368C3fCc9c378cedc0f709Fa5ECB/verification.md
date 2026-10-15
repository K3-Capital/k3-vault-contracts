# Ethereum mainnet — USDe Enhanced Yield deployment verification

## Verdict and scope

Deployment wiring and local bytecode provenance verified, with operational and explorer caveats. All five application creation payloads and live runtimes match source commit `24203cb8dac7d8810e63f5846151076e9ab55c61`, with the correct constructor arguments and immutable substitutions. All three CREATE3 helper runtimes, deterministic address derivations, initialization and the checked permission boundaries also match.

Etherscan publishes source for all five contracts. The coordinator and wrapper proxy have **Exact Match** verification; the implementation, beacon and Staging have **Similar Match** publication. Explicit standard-JSON submissions for the latter three returned `Already Verified`, not a Full Match upgrade. These explorer labels are distinct from the exact local bytecode checks. See the [explorer evidence](etherscan-status.json).

Registry status is `deployed-pending-activation`. The vault is **unpaused**, so that label is not an on-chain deposit gate. No funded mainnet smoke test was performed. The settlement authority has empty code, nonce zero and zero ETH at the pinned snapshot. Signing control and operational readiness were not established. This report is not an audit or authorization to accept public deposits.

Only read-only RPC, isolated `eth_call` simulations and explorer source publication were performed. No wallet was unlocked, transaction signed/broadcast, ownership changed, or beacon upgraded. Local `.env` files were not edited; secrets and endpoint credentials are excluded from this record.

## Deployment identity

- Chain: Ethereum mainnet, ID `1`.
- Stable integration address: `0x333333c5DEF8368C3fCc9c378cedc0f709Fa5ECB`.
- Vault: `USDe Enhanced Yield` / `USDe+`, 18 asset/share decimals.
- Asset: [`0x4c9EDD5852cd905f086C759E8383e09bff1E68B3`](https://etherscan.io/token/0x4c9EDD5852cd905f086C759E8383e09bff1E68B3), reporting `USDe` / `USDe`. This checks address and metadata, not issuer or economic risk.
- Owner and beacon upgrade authority: `0x349bB895dB64f74AB9788693a16Ee03776195504`.
- Settlement authority: `0xbDd42d97cb0341b77E73F8F6EC54cEcD068aef6B`.
- Source: [`24203cb8dac7d8810e63f5846151076e9ab55c61`](https://github.com/K3-Capital/k3-vault-contracts/commit/24203cb8dac7d8810e63f5846151076e9ab55c61), matching the broadcast's `24203cb` provenance. Solidity sources, vendored libraries, deployment scripts and compiler settings in the fresh `origin/main` worktree match that commit.
- Compiler: Solidity `0.8.30+commit.73712a01`, EVM `osaka`, optimizer enabled with 200 runs, no via-IR, IPFS bytecode metadata, CBOR enabled. Exact remappings are in [deployment.json](deployment.json).
- Initial reproduction used installed Foundry `1.1.0-stable` (`d484a00089d789a19e2e43e63bbb3f1500eb2cbf`). Checks were also run with isolated Foundry `1.7.1` (`4072e48705af9d93e3c0f6e29e93b5e9a40caed8`) without replacing the user's installed toolchain.

| Component | Address | Etherscan source status |
| --- | --- | --- |
| AtomicDeployment | [0x69Efc4048c041615b7286E9491240F3355fA2Af7](https://etherscan.io/address/0x69Efc4048c041615b7286E9491240F3355fA2Af7#code) | Exact Match |
| SmartAccountWrapper | [0xdA324F7df50a716c66d48d33F2543Fe50Ae27B5e](https://etherscan.io/address/0xdA324F7df50a716c66d48d33F2543Fe50Ae27B5e#code) | Similar Match |
| UpgradeableBeacon | [0x99DaC42A6A3975d9C2a4dD2dc3554F1270666F8F](https://etherscan.io/address/0x99DaC42A6A3975d9C2a4dD2dc3554F1270666F8F#code) | Similar Match |
| BeaconProxy | [0x333333c5DEF8368C3fCc9c378cedc0f709Fa5ECB](https://etherscan.io/address/0x333333c5DEF8368C3fCc9c378cedc0f709Fa5ECB#code) | Exact Match |
| Staging | [0x97a7f837f56A77842e10Bbab5327fBa38303CB40](https://etherscan.io/address/0x97a7f837f56A77842e10Bbab5327fBa38303CB40#code) | Similar Match |

## Successful atomic deployment

Transaction: [`0xede10f9e7053e1fbab42bfa70840616e555bb04a36022c7feace5215e3a475d4`](https://etherscan.io/tx/0xede10f9e7053e1fbab42bfa70840616e555bb04a36022c7feace5215e3a475d4).

- Receipt status `1`, block `26192428`, timestamp `2026-10-14T18:06:47Z`.
- Block hash `0x5cf0dac5acdd2bc9c63492fb0f2a28bed87b7b48716107bd2597f42ef7de84ed`.
- Sender `0x43F4600D98Ae531D7e5F1f8FF68ef97779d31641`, nonce `60`, value `0`.
- Target is canonical CREATE2 deployer `0x4e59b44847b379578588920cA78FbF26c0B4956C`.
- Gas used `5195746`, effective gas price `258397938` wei; receipt-derived cost `0.001342570052771748` ETH.

One top-level CREATE2 transaction created the coordinator, which atomically created the implementation, beacon, initialized wrapper and Staging before returning. This is not the legacy multi-transaction sequence.

The immutable successful broadcast is [broadcast/Deploy.s.sol/1/run-1792001209.json](../../../broadcast/Deploy.s.sol/1/run-1792001209.json), SHA-256 `d098e7004ddc0a0030207512804ef8fa57010a05b6885a22a98997f98003fb4b`. Sender, destination, nonce, value, chain ID and exact calldata match the live transaction; receipt hash/block/index/status/gas/logs match the live receipt. No hash-to-payload misassociation was found. The earlier receipt-free `run-1792000744.json` and mutable `run-latest.json` are not archived as deployment evidence.

The public base/coordinator salts and all derived salts are recorded in the manifest. CREATE3 helper addresses were independently derived from the coordinator and role salts; each nonce-one child equals its application address. The helpers remain on-chain with runtime `0x363d3d37363d34f0` and nonce `2`:

| CREATE3 target | Helper |
| --- | --- |
| implementation | `0x10153Cea54EBd06EA5aBAe37905316a0164f361b` |
| beacon | `0x3E210c789278E3cC83D4246070211AF0E4A09e99` |
| wrapper | `0xf727a27eBfDcb267c6025bFe643A91b50AcD1528` |

The spent helpers can create later-nonce children but cannot replace the deployed nonce-one children; they have no vault authority.

## Pinned state, bytecode and authorization

Snapshot: block `26192515`, timestamp `2026-10-14T18:24:11Z`, hash `0x5d1ab30b83594536f247fa60dda91af978eb5295f071153c031a1acef4c9794b`. Views, five application runtimes and proxy slots were rechecked unchanged at block `26192585`, timestamp `2026-10-14T18:38:23Z`, hash `0x8d24152bb97d392fdb5667a9c828b64a0b5020dbe53ecdb6aa1bf6516e51f992`.

[onchain-evidence.json](onchain-evidence.json) retains the live transaction/receipt, pinned runtime code, configuration views, storage words, CREATE3 derivations and simulation requests/responses. Its digest is recorded in the manifest.

| Contract | Runtime bytes | Keccak-256 |
| --- | ---: | --- |
| AtomicDeployment | 258 | `0xf53e505b333d040d803d9db3c4e6ff337536df21e59c8230136125c66a44be44` |
| SmartAccountWrapper | 19167 | `0xad4777be5d6dcef322b94b7d0d30a1cbf5e8f44f98b011cf7ba4490afb836cd5` |
| UpgradeableBeacon | 644 | `0x0ce4415c191fe5f2c89e67fd04fc646aa9b61958a01026bf58029708b8bd2a51` |
| BeaconProxy | 283 | `0xecb24c5b6eddd61cac44c054b7f500eb69c5fa8aeea5cfa82962125ac817f567` |
| Staging | 577 | `0x74eb5803cc6b67f52d3ea0570dc46bef3f5bee4071475c6b7b16a41e8de1f93d` |
| Each CREATE3 helper | 8 | `0x0b130a5cdfe5920e22336512f736f182f31e18977d284dba00dcd14b698071a3` |

All runtimes match local artifacts exactly after substituting coordinator implementation/beacon/wrapper, proxy beacon and Staging vault immutables. Application creation bytecode and constructor payloads match the successful broadcast; coordinator creation matches the live CREATE2 payload. Constructor arguments were also independently ABI-encoded from the pinned configuration.

- Beacon slot and immutable beacon point to the recorded beacon; ERC-1967 implementation/admin slots are zero.
- Beacon implementation/owner, wrapper owner/asset/settlement authority/name/symbol/decimals, `share()` and Staging `vault()` match.
- Pending owner is zero. Owner has the effective default admin role; settlement authority does not.
- Proxy initialization version is `1`; implementation initializers are disabled (`uint64.max`). Both initialization/reinitialization probes revert with `InvalidInitialization()`.
- Epoch `1`, frozen epoch `0`, total supply/assets/redemption reserves/surplus all zero. Wrapper/Staging asset balances and Staging share balance are zero. The vault is unpaused.
- All **16** isolated authorization simulations passed: settlement authority can close and reaches the no-frozen-epoch settlement guard; owner/deployer cannot close and owner cannot settle; owner can pause/change the settlement authority/upgrade the beacon while the checked unauthorized actors are rejected; an outsider cannot move staged tokens; both initializer guards reject replay.

Positive `eth_call` probes prove the caller gate, not control of the actor's keys or persistent execution. The upgrade probe targets the current implementation, and no upgrade occurred. Reaching `SA__NoFrozenEpoch()` does not demonstrate a successful settlement or correct NAV.

## Explorer publication caveat and verifier fix

Etherscan V2 read-back and public code pages agree on the statuses above. The evidence retains all five submission GUIDs, final responses, source/ABI digests, reported and expected constructor arguments, and Similar Match reference addresses. For beacon and Staging, the Similar Match response omits constructor arguments; that omission is not treated as a successful constructor check. Correct constructor payloads and exact local checks remain in this record.

[Etherscan's documented policy](https://docs.etherscan.io/contract-verification/common-verification-errors#similar-match-found) requires contacting support to upgrade an existing Similar Match to Full Match. No support request was sent. If Full Match is required, provide the three addresses, deployment transaction, source commit/settings and expected constructor payloads in `etherscan-status.json`. Do not label `Already Verified` as Exact Match.

The installed Forge `1.1.0` uses the retired V1 default, and the reported preliminary V2 ABI lookup failed with `Missing or unsupported chainid` despite supplying a V2 URL. The precise internal mechanism was not established by source inspection. Direct V2 requests with explicit `chainid=1` succeeded. A read-only dummy-key status request and the updated real wrapper with isolated Forge `1.7.1` reached V2 and returned `Invalid API Key`, rather than the URL/chainid errors. The verification wrapper now rejects outdated Forge, chooses nonempty V2 defaults and exports the resolved URL so Foundry's dotenv autoload cannot restore an empty override. Compiler/EVM settings and Solidity code were not changed.

## Activation and validation

Owner runtime code is empty, nonce `38`, native balance `21576165449115159` wei. Settlement authority runtime code is empty, nonce `0`, balance `0`. Empty code is consistent with an EOA but does not prove key possession or rule out intended counterfactual setup. Neither address currently provides observed on-chain multisig/timelock protection.

Before activation, confirm signing control and intended account setup; fund gas or verify sponsorship; approve bootstrap capital and an ongoing real-share floor, custody/NAV reconciliation, liquidity and zero-share settlement policies; and complete production security review. Under separately authorized transactions, perform the full request/settle/claim deposit and redemption cycle and append its receipts before marking active. No smoke evidence file exists because no funded cycle was authorized or performed.

Local verification returned 91 Solidity tests passed, zero failed/skipped; 33 miner tests and 9 offline verifier tests passed. Foundry `1.7.1` formatting and size checks passed. The older installed formatter reports unrelated baseline formatting differences; source was not reformatted to accommodate it. All 36 registry tests passed with a canonical temporary directory, and all three deployment manifests validated. The default macOS temporary-directory symlink triggers an existing path-equality test failure, reproduced on the untouched checkout; `TMPDIR=/private/tmp` avoids that environment issue without changing validator code. Standard registry commands are:

```sh
python3 -m unittest deployments/test_validate.py
python3 deployments/validate.py
```

These checks validate local records, not live chain state. Preserve the original deployment provenance and append future activation/upgrade evidence under the [registry policy](../../README.md).
