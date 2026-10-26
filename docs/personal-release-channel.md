# Personal release channel

This fork serves two purposes: source branches for potential upstream contributions,
and a HACS channel containing only reviewed personal component releases.
It is not an official HA-MCP release channel.

## Approved pair and provenance

The first personal channel release is **2.2.2.1**: upstream component **2.2.2**,
personal revision **1**, paired with **ha-mcp==8.7.0**. The previous personal
installation called this component 2.2.3. Renaming it to 2.2.2.1 clarifies its
upstream base; it does not remove the personal patches. Only the component
manifest and version constant change for this migration.

`personal-build.json` records the accepted base commit, patch provenance and
complete component file checksums. Author and committer email addresses on
personal source commits use the GitHub noreply identity. Commits and release
tags are signed. Upstream commits retain their original attribution.

## Ownership and safety

HACS tracks **akioli/ha-mcp**, replacing the official mirror. The default branch
is `personal/release-channel`; `master` remains available as an upstream base.
The HACS default-branch download option is hidden. Only explicitly approved
personal releases are published on this fork; no upstream release is copied
automatically. GitHub Actions on this fork are disabled at repository level,
so inherited upstream workflows cannot publish, mutate or synchronize it.

Both HA MCP update entities stay disabled, and automatic server updates stay
off. The embedded server stays pinned to the recorded exact package version.
HACS manages component files, not the separate server pin. Routine HA update
buttons must not bypass the coordinated maintenance process.

## Future updates

1. The existing monitor checks both official upstream projects and reports new
   stable releases; it does not deploy or change this fork.
2. Select immutable upstream component and server versions. Inspect the three
   personal protections; retire only behavior proven covered upstream, and
   adapt the remaining patches on isolated source branches with their tests.
3. Use the local ha-mcp-maintenance skill for candidate validation, fresh backup,
   coordinated deployment, live acceptance and rollback. Preserve existing
   HomeKit identity, pairings, YAML layout, flags and release-monitor history.
4. Use `UPSTREAM_COMPONENT.PERSONAL_REVISION` version numbers in both the manifest
   and component constant: e.g. 2.2.2.1, 2.2.2.2, then 2.2.3.1. Verify version
   ordering and compatibility before adopting a new numbering scheme.
5. Refresh personal-build.json from the exact candidate. Keep source patches
   separable for upstream PRs. No personal version/channel commits belong in
   upstream bug-fix PRs.
6. With explicit publication and deployment authorization, sign the source
   commits and a unique version tag, publish clear release notes, and apply
   the tested pair. Never move a published release tag. Preserve manual updates
   and disable any replacement update entities created by HACS.

Passing checks does not authorize publishing or deployment. Keep failures and
skips visible; an incomplete acceptance must not be described as success.
A return to upstream is a deliberate source migration after all required
protections have shipped upstream and passed the maintenance checks.

## Validate the published snapshot

Verify version parity, the complete file list and SHA-256 hashes in
personal-build.json against the exact release tag and the installed component.
Run the relevant source tests. Use the release tag's commit identity rather
than a moving branch as deployment evidence. Historical acceptance on an older
Core version is not a claim of a fresh full suite on the current Core.

To change HACS tracking without uninstalling a running component, the installed
HACS 2.0.5 has `hacs/repositories/remove` (plural), which unregisters a custom
repository without deleting its files. `hacs/repository/remove` (singular)
uninstalls and deletes component files. Verify the current HACS implementation
before reusing this distinction; never edit HA .storage files directly.
