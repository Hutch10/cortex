# Cortex Security & Hardening Note

## Current Status: 0.9.0-beta.1

Cortex is currently in a Public Beta state. The fundamental architectural guarantees (immutability, append-only constraints, cryptographic hash chains) are mathematically sound and implemented correctly in the SQLite ledger.

However, there is a **significant security limitation** in the current beta release regarding API entry points:

### 1. Signature Enforcement Gap
Currently, the `/api/v1/core/append` endpoints require an `actor_id` and a `signature` field in the payload to adhere to the Cortex Primitive specifications.
**Limitation:** The API does *not* currently validate that the `signature` is a cryptographically valid ED25519 (or similar) signature matching a registered public key for the `actor_id`.

**Impact:** Any user with network access to the FastAPI server can impersonate another `actor_id` simply by sending a forged string in the `signature` field. 

### 2. Mitigation Strategy for Production (v1.0.0)
Before Cortex can achieve General Availability (GA), the following Security Hardening Plan must be executed:
1. **Tenant/Key Registry:** Cortex must implement a minimal Public Key registry for `actor_id`s.
2. **Auth Middleware:** A strict FastAPI middleware must be written that intercepts all POST requests, extracts the raw JSON payload and the `signature`, and uses `pynacl` to cryptographically verify the signature against the actor's public key before allowing the append to proceed.
3. **Transport Security:** The API must run strictly over HTTPS/TLS, preventing man-in-the-middle payload modification prior to signature hashing.

### Beta Recommendations
For `0.9.0-beta.1`, Cortex should only be deployed in physically isolated, trusted internal networks (e.g., behind a strict corporate VPN or VPC) where malicious internal actor impersonation is an accepted beta risk. **Do not expose Cortex Beta directly to the public internet.**
