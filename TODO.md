# Product roadmap

This document tracks planned work beyond the current MVP. The deployed baseline
already includes authenticated users, named JWT collector identities, collector
heartbeats and inventory, protocol-v1 compatibility checks, remote configuration,
TLS ingress, searchable snapshots and summaries, and calendar/episode navigation.

## Implemented small improvements

- Collector-scoped calendar activity and hour/day episode-summary cards, including
  sidebar navigation. The all-collector view retains generated global summaries.
- `/healthz` database read/write and schema checks with a safe public response.
- Search and collector inventory pagination (20 items per page), with a 1,000-result
  search cap and a 5,000-episode semantic candidate cap.
- One-time token copying and a collector launch command with a hidden token prompt.
- Optional OIDC login, automatic reader provisioning, and admin-managed user roles,
  blocking, unblocking, and deletion. Local administrator login remains available.

These changes are implemented in source; live OIDC provider configuration and
end-to-end deployment verification are separate steps.

## 1. Collector identity and inventory

- Add notifications for collectors that remain offline beyond a configured
  threshold.
- Allow administrators to rotate a collector credential without replacing its
  identity or historical ownership.
- Add bulk owner/label editing after the single-collector workflow has settled.

## 2. Search scopes and navigation

- Filter searches by owner, session, tab, command, working directory, label, and
  date range. Collector-scoped search is already supported.
- Support saved searches and bookmarks.
- Add a global activity timeline across collectors.
- Group repetitive results by task or session.
- Show how a natural-language query was interpreted and allow corrections.

## 3. Collector transport hardening

- Add optional mutual TLS for environments that require client certificates in
  addition to the current per-collector JWT authentication.
- Add credential rotation; permanent collector revocation is already supported.
- Add replay protection on top of the current protocol version and upload
  deduplication checks.
- Extend the current durable local queue and retry behavior with compression,
  explicit backpressure, and bandwidth limits.

Detailed design notes are in `deploy/SECURITY_ROADMAP.md`.

## 4. Users, roles, and SSO

- OIDC SSO and `admin`/`reader` roles are implemented; add an `operator` role
  once its permissions have been defined.
- Scope collectors and search results to users or teams.
- Add access-controlled, expiring links to session moments.
- Record an audit log for login, search, export, deletion, and configuration
  activity.

## 5. Retention and privacy

- Add global and per-collector retention policies and storage quotas.
- Add configurable scrollback truncation by age and maximum retained size.
- Add encryption-at-rest options.
- Add capture exclusions for commands, tabs, paths, and applications.
- Add a temporary privacy mode and a visible recording indicator.
- Allow redaction or deletion of a selected time interval.
- Report secret-filter activity without exposing detected values.
- Add consent and usage notices for shared machines.

## 6. Multi-tab playback

- Play all tabs from a session on one synchronized timeline.
- Reproduce tab switches at their original timestamps.
- Add markers for commands, errors, builds, Git operations, and summaries.
- Add adjustable playback speed, idle-time skipping, and snapshot diff mode.
- Export sanitized text or an asciinema-compatible recording.

## 7. Production storage and operations

- Add PostgreSQL support for multi-user and Kubernetes deployments while
  retaining SQLite for standalone installations.
- Evaluate object storage for compressed raw session data.
- Add database backup, restore, migration, and retention jobs.
- Add Prometheus metrics, structured logs, and an admin diagnostics page. Basic
  and expanded readiness checks are tracked in the small-improvements section.
- Add resource usage and storage growth forecasts.

## 8. Reporting and automation

- Generate weekly, project, user, and collector reports in addition to hourly
  and daily summaries.
- Extract tasks, outcomes, failures, and unfinished work.
- Support custom summary templates per team.
- Track the model and prompt version used for every generated summary.
- Allow summaries to be regenerated after a model or prompt change.
- Add optional notifications for failed builds and configurable events.

## 9. SSH and session-recorder integrations

- Import recordings from common SSH and terminal session loggers, including
  `tlog`, Linux audit/sudoreplay I/O logs, `script`/typescript timing files,
  and asciinema casts.
- Evaluate native integrations for centralized access systems such as Teleport.
- Preserve source host, remote user, destination host, command, terminal size,
  timestamps, and recorder identity as searchable metadata.
- Normalize imported recordings into the same timeline and playback model as
  Zellij sessions without losing the original recording.
- Support both file import and incremental ingestion from remote collectors.
- Deduplicate sessions that were captured by both Zellij and an SSH recorder.
- Apply the same secret filtering, retention, access control, and audit policies
  to imported recordings.
- Display recording provenance and integrity-verification status in the UI.
