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

### Required dependencies — now resolved

Per the MineColonies 1.1.1365 release notes, it hard-requires three
more libraries. All three found on CurseForge (not Modrinth — same
situation as MineColonies/Structurize, none of `multipiston`,
`blockui`, `domum-ornamentum` resolve there) and added the same way:
downloaded directly from CurseForge's CDN, hashed locally.

- `multipiston.pw.toml` — file 7097877, project 303278,
  `multipiston-1.2.58-1.21.1.jar`, NeoForge, MC 1.21.1.
- `blockui.pw.toml` — file 7790469, project 522992,
  `blockui-1.0.211-1.21.1-snapshot.jar`, NeoForge, MC 1.21.1.
- `domum-ornamentum.pw.toml` — file 8311478, project 527361,
  `domum-ornamentum-1.0.234-snapshot-main.jar`, NeoForge, MC 1.21.1.

`index.toml` regenerated again — 28 entries total now.

### Action items
- [x] Confirm NeoForge build availability for MineColonies/Structurize
      at 1.21.1 — done via CurseForge.
- [x] Source real download URL + hash — done, downloaded and hashed
      locally.
- [x] Add both to `packwiz/mods/` and update `index.toml`.
- [x] Find and add MultiPiston, BlockUI, and Domum Ornamentum the same
      way (CurseForge search + direct CDN download + local sha256).
- [ ] Once all deps are in, do a real server boot test — this pack has
      never actually been launched, only assembled from metadata.
- [ ] JEI, Journeymap-min-version, and Dynamic Trees are listed as
      *optional* deps in the MineColonies changelog — JourneyMap is
      already in the pack; JEI is not (REI is present instead, which
      may or may not satisfy whatever soft-integration MineColonies
      expects — worth checking in-game).

## Full-pack dependency audit (2026-07-29)

Checked every Modrinth-sourced mod's real declared `dependencies`
field (not guesswork) plus jar-in-jar contents, for NeoForge 1.21.1.
Found 9 more required libraries missing, none embedded jar-in-jar:

| Mod that needs it | Library added |
|---|---|
| Modern Industrialization, Applied Energistics 2 | GuideME |
| Integrated Dynamics | Common Capabilities, Cyclops Core |
| Chipped | Athena, Resourceful Lib |
| Supplementaries | Moonlight Lib |
| Terralith | Lithostitched |
| Inventory Profiles Next | Kotlin for Forge, libIPN |

All 9 added (`packwiz/mods/`), `index.toml` regenerated — 37 entries
total now. Transitive deps checked too (Common Capabilities needs
Cyclops Core, libIPN needs Kotlin for Forge — both already covered).

- [x] Full dependency audit across all 28 mods (now 37 with libs).
- [ ] **Still open:** WorldEdit CUI (Unofficial Forge Port) is in the
      pack but the base **WorldEdit** mod is not — CUI is a visual
      overlay only, does nothing without WorldEdit itself installed.
      Not a crash risk, just a dead mod until WorldEdit is added.
- [ ] Still no real boot test performed — do this before calling the
      pack "done."
