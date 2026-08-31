# Transport and authentication roadmap

The current UI and collector-admin endpoint is plain HTTP and unauthenticated.
Ingestion requires a server-generated per-collector HS256 JWT. The deployment must
only be used on a trusted network. Do not expose it to the public Internet.

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
6. UI authentication remains separate, ideally through an existing OIDC proxy.

Ed25519 authentication will replace the MVP JWT protocol before any
Internet-facing deployment. Until then, JWTs provide named identities and
revocation checks on a trusted network, not replay resistance on an unencrypted
transport.
