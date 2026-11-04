# Transport and authentication roadmap

Browser access requires a local account or optional native OIDC login.
Administration requires the `admin` role and CSRF validation. New OIDC users
receive `reader` access to the shared recording library; per-user/team recording
permissions remain planned. See `README.md` for OIDC setup and revocation behavior.

Ingestion requires a server-generated per-collector HS256 JWT. The standalone
HTTP listener must sit behind trusted TLS ingress for remote access; OIDC
requires HTTPS. JWT ingestion does not provide request-level replay protection.

## TLS

The intended Kubernetes implementation is:

1. Add a cert-manager `Certificate` for the Ingress hostname.
2. Store the certificate in a namespaced TLS Secret.
3. Configure the Traefik Ingress with `websecure`, `tls.secretName`, and an HTTP
   to HTTPS redirect.
4. Give the collector a configurable CA bundle and require certificate
   verification. Never add an insecure-skip-verify option.

## Key authentication

The intended protocol is per-collector Ed25519 request signing rather than a
shared bearer token:

1. Each collector owns a private key that never leaves the workstation.
2. Kubernetes stores only collector IDs and public keys.
3. Every request includes collector ID, timestamp, nonce, body digest, and a
   signature over the canonical request.
4. The server enforces a short clock-skew window and persists recently used
   nonces to prevent replay.
5. Public keys can be independently revoked and rotated.
6. UI authentication remains separate through local sessions or native OIDC.

Ed25519 authentication will replace the MVP JWT protocol before any
Internet-facing deployment. Until then, JWTs provide named identities and
revocation checks on a trusted network, not replay resistance on an unencrypted
transport.
