//! Native, offline search matching DeployAll and Solady CREATE3.
use std::io::{self, Read};
use tiny_keccak::{Hasher, Keccak};

const PROXY_HASH: &str = "21c35dbe1b344a2488cf3321d6ce542f8e9f305544ff09e4993a62319a497c1f";

fn decode(text: &str) -> Result<Vec<u8>, String> {
    if text.len() % 2 != 0 || !text.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid hex input".into());
    }
    (0..text.len()).step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).map_err(|_| "invalid hex input".into()))
        .collect()
}

fn hex(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}

fn hash(parts: &[&[u8]]) -> [u8; 32] {
    let mut state = Keccak::v256();
    for part in parts { state.update(part); }
    finish(state)
}

fn finish(state: Keccak) -> [u8; 32] {
    let mut output = [0u8; 32];
    state.finalize(&mut output);
    output
}

fn child(coordinator: &[u8], salt: &[u8], label: &[u8], proxy_hash: &[u8]) -> [u8; 20] {
    let derived = hash(&[salt, label]);
    let proxy = hash(&[&[0xff], coordinator, &derived, proxy_hash]);
    let address = hash(&[&[0xd6, 0x94], &proxy[12..], &[1]]);
    address[12..].try_into().unwrap()
}

fn increment(salt: &mut [u8; 32]) -> bool {
    for byte in salt.iter_mut().rev() {
        let (next, overflow) = byte.overflowing_add(1);
        *byte = next;
        if !overflow { return true; }
    }
    false
}

fn matches(address: &[u8], prefix: &str) -> bool {
    // Compare nibbles without allocating hex strings on the hot path.
    prefix.bytes().enumerate().all(|(i, digit)| {
        let expected = (digit as char).to_digit(16).unwrap() as u8;
        let nibble = if i % 2 == 0 { address[i / 2] >> 4 } else { address[i / 2] & 15 };
        nibble == expected
    })
}

fn run() -> Result<bool, String> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).map_err(|_| "cannot read input")?;
    let lines: Vec<_> = input.lines().collect();
    if lines.len() != 7 { return Err("expected seven input lines".into()); }
    let factory = decode(lines[0])?;
    if factory.len() != 20 { return Err("CREATE2 deployer must be 20 bytes".into()); }
    let before = decode(lines[1])?;
    let after = decode(lines[2])?;
    let mut salt: [u8; 32] = decode(lines[3])?.try_into().map_err(|_| "salt must be 32 bytes")?;
    let prefix = lines[4];
    if prefix.len() > 40 || !prefix.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("prefix must have at most 40 hex digits".into());
    }
    let limit: u64 = lines[5].parse().map_err(|_| "invalid attempt limit")?;
    if limit == 0 { return Err("attempt limit must be positive".into()); }
    if lines[6] != "wrapper" { return Err("only wrapper targets are supported".into()); }
    let proxy_hash = decode(PROXY_HASH)?;
    // Salt is inside constructor arguments. Cache only the invariant initcode prefix,
    // not the initcode hash, which changes on every candidate.
    let mut initial = Keccak::v256();
    initial.update(&before);
    for index in 0..limit {
        let mut state = initial.clone();
        state.update(&salt);
        state.update(&after);
        let initcode_hash = finish(state);
        let derived = hash(&[&salt, b"atomic-deployment"]);
        let coordinator_hash = hash(&[&[0xff], &factory, &derived, &initcode_hash]);
        let coordinator = &coordinator_hash[12..];
        let wrapper = child(coordinator, &salt, b"wrapper", &proxy_hash);
        if matches(&wrapper, prefix) {
            let implementation = child(coordinator, &salt, b"implementation", &proxy_hash);
            let beacon = child(coordinator, &salt, b"beacon", &proxy_hash);
            println!("{{\"salt\":\"0x{}\",\"attempts\":{},\"initcodeHash\":\"0x{}\",\"create2Deployer\":\"0x{}\",\"addresses\":{{\"coordinator\":\"0x{}\",\"implementation\":\"0x{}\",\"beacon\":\"0x{}\",\"wrapper\":\"0x{}\"}}}}",
                hex(&salt), index + 1, hex(&initcode_hash), hex(&factory), hex(coordinator),
                hex(&implementation), hex(&beacon), hex(&wrapper));
            return Ok(true);
        }
        if !increment(&mut salt) {
            if index + 1 == limit {
                eprintln!("No match in {limit} candidates. Exhausted bytes32 salt range; no resume salt");
                return Ok(false);
            }
            return Err("exhausted bytes32 salt range".into());
        }
        if (index + 1) % 1_000_000 == 0 { eprintln!("Searched {} candidates", index + 1); }
    }
    eprintln!("No match in {limit} candidates. Resume with --start 0x{}", hex(&salt));
    Ok(false)
}

fn main() {
    match run() {
        Ok(true) => (),
        Ok(false) => std::process::exit(2),
        Err(error) => { eprintln!("Error: {error}"); std::process::exit(1); }
    }
}
