# TODO / Tech Debt

## MineColonies + Structurize (NeoForge 1.21.1)

Removed from `packwiz/` during the Fabric → NeoForge 1.21.1 migration
(commit `bf1e51f` on this branch). The previous entries for both mods
contained fabricated placeholder data (fake hashes, fake Modrinth
project IDs that resolved to unrelated mods) — they were never real,
not something this migration broke.

Both mods are confirmed alive and maintained for MC 1.21.1 via the
official `ldtteam` GitHub repos:
- https://github.com/ldtteam/minecolonies
- https://github.com/ldtteam/structurize

Their Modrinth listings are stale/unreliable (MineColonies project on
Modrinth is stuck at 1.18.2, Forge-only, last touched years ago), so
they can't be safely auto-sourced from Modrinth the way the other 20
mods in this pack were.

**Do not** pull these from third-party mirror sites (e.g.
minecraft-inside.ru) — no way to verify file integrity, real risk of
tampered jars (see the 2023 fractureiser incident for why this matters
in the Minecraft mod ecosystem).

### Action items
- [ ] Confirm official NeoForge (vs Forge) build availability for
      MineColonies 1.21.1 and Structurize 1.21.1 — check CurseForge
      or the GitHub release assets/linked download page directly.
- [ ] Source real download URL + hash from an official channel
      (CurseForge page, or ldtteam's own maven/CDN if it exposes one).
- [ ] Add both back to `packwiz/mods/` with `packwiz cf add` (if using
      CurseForge as source) or equivalent manual `.pw.toml` entries
      with a verified hash.
- [ ] Update `packwiz/index.toml` accordingly.
- [ ] Re-verify the dependency chain: MineColonies requires
      Structurize, BlockUI, MultiPiston, Domum Ornamentum (per the
      1.1.1365 release notes) — check whether the last three also
      need adding to the pack.
