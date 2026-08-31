# Product roadmap

This document tracks planned work beyond the current MVP. The deployed baseline
already includes authenticated users, named JWT collector identities, collector
heartbeats and inventory, protocol-v1 compatibility checks, remote configuration,
TLS ingress, searchable snapshots and summaries, and calendar/episode navigation.

## Small next improvements

These are intentionally narrow changes that reuse the current SQLite schema and
web application and should not require new infrastructure:

- Show collectors as online, stale, or offline using configurable heartbeat-age
  thresholds. Sort unhealthy collectors first and show their age in friendly form.
- Add a collector selector to search and calendar pages. Preserve the selected
  collector in result, episode, day, and hour links.
- Expand `/healthz` with database readability/writability and schema-version
  checks, while keeping the response safe for unauthenticated probes.
- Add simple pagination and result-count limits to search and collector inventory.
- Add one-click copying of a newly generated collector token and a ready-to-paste
  collector command. Continue displaying the token only once.

## 1. Collector identity and inventory

- Add notifications for collectors that remain offline beyond a configured
  threshold. Basic online/stale/offline presentation is tracked above.
- Allow administrators to rotate a collector credential without replacing its
  identity or historical ownership.
- Add bulk owner/label editing after the single-collector workflow has settled.

## 2. Search scopes and navigation

- Filter searches by collector, owner, session, tab, command, working directory,
  label, and date range.
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

- Add OIDC-based SSO.
- Add `admin`, `operator`, and `reader` roles.
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
