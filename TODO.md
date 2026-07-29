# TODO / Tech Debt

## Real boot test results (2026-07-29) — 3 infra bugs found and fixed

Ran the pack against the actual `itzg/minecraft-server` container (not
just metadata checks). All three were pre-existing infra bugs, not
new breakage from the NeoForge migration:

1. **`server/docker-compose.yml`**: `MODS_FILE: "/data/packwiz-bootstrap.jar"`
   pointed at a file nothing ever creates. Fixed to
   `PACKWIZ_URL: "file:///packwiz/pack.toml"` (the correct itzg env var —
   see https://docker-minecraft-server.readthedocs.io/en/latest/mods-and-plugins/packwiz/).
2. **`packwiz/pack.toml`**: was missing the required `[index]` block
   (file/hash-format/hash pointing at `index.toml`). packwiz-installer
   refused to even parse the pack without it. Fixed.
3. **`server/config/server.properties`** (git-tracked): has a
   hardcoded empty `rcon.password=`. Since `COPY_CONFIG_DEST=/data`
   copies this over `/data/server.properties` on every boot, the
   `RCON_PASSWORD` env var from `.env` never actually takes effect —
   RCON stays disabled regardless of what's in `.env`. **Not yet
   fixed** — don't want to commit a real password into this tracked
   file. Needs either: strip `rcon.password` from the template
   entirely (so mc-image-helper's own env-based property injection
   can set it, if `OVERRIDE_SERVER_PROPERTIES` allows), or move RCON
   password injection to a startup script instead of a static file.

With all 3 mods-related fixes applied, the full 38-mod pack booted
clean: `Done (18.970s)!`, MineColonies completed full Compat Discovery
(confirms its whole dependency chain — Structurize, MultiPiston,
BlockUI, Domum Ornamentum — actually works at runtime, not just in
theory). Also confirmed client/server mod-list enforcement works as
expected (unmodded client gets cleanly rejected: `Incompatible client!
Please use NeoForge 21.1.244`).

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
- [x] Added base **WorldEdit** (7.3.8, NeoForge, MC 1.21.1, no
      dependencies) so WorldEdit CUI has something to attach to.
      `index.toml` now 38 entries.
- [ ] Still no real boot test performed — do this before calling the
      pack "done."
