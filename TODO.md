# TODO / Tech Debt

## MineColonies + Structurize (NeoForge 1.21.1)

**Update:** MineColonies and Structurize have been added back to
`packwiz/mods/` with real, verified data — sourced directly from
CurseForge (their actual official distribution channel; GitHub
releases for both repos only contain changelogs with zero attached
file assets, so GitHub itself can't be used as a download source
despite confirming the mods are alive and maintained).

- `minecolonies.pw.toml` — CurseForge file 8532544, project 245506,
  `minecolonies-1.1.1365-1.21.1-snapshot.jar`, NeoForge, MC 1.21.1.
  Downloaded directly and hashed locally (sha256), not trusted from
  a third party — verified against the live CurseForge CDN response.
- `structurize.pw.toml` — CurseForge file 8398574, project 298744,
  `structurize-1.0.832-1.21.1-snapshot.jar`, NeoForge, MC 1.21.1.
  Same verification approach.

`index.toml` has been regenerated to include both (25 entries total).

**Do not** pull these from third-party mirror sites (e.g.
minecraft-inside.ru) — no way to verify file integrity, real risk of
tampered jars (see the 2023 fractureiser incident for why this matters
in the Minecraft mod ecosystem).

### Remaining gap: still-missing required dependencies

Per the MineColonies 1.1.1365 release notes, it hard-requires three
more libraries that are **not yet in the pack**:
- MultiPiston 1.2.51-1.21.1-snapshot (or above)
- BlockUI 1.0.199-1.21.1-snapshot (or above)
- Domum Ornamentum 1.0.223-snapshot (or above)

None of these resolved on Modrinth under their obvious slugs
(`multipiston`, `blockui`, `domum-ornamentum` all 404). They're likely
also CurseForge-primary like MineColonies/Structurize were. **Without
these three, MineColonies will not start.**

### Action items
- [x] Confirm NeoForge build availability for MineColonies/Structurize
      at 1.21.1 — done via CurseForge.
- [x] Source real download URL + hash — done, downloaded and hashed
      locally.
- [x] Add both to `packwiz/mods/` and update `index.toml`.
- [ ] Find and add MultiPiston, BlockUI, and Domum Ornamentum the same
      way (CurseForge search + direct CDN download + local sha256).
- [ ] Once all deps are in, do a real server boot test — this pack has
      never actually been launched, only assembled from metadata.
