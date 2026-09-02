#!/usr/bin/env bash
# install-client-macos.sh - Install the Minecraft Infra Pack modpack on macOS via PolyMC.
#
# Usage: bash install-client-macos.sh
#
# The script will:
#   1. Locate (or offer to install) PolyMC in ~/Applications or /Applications
#   2. Verify (or offer to install) Java 21+
#   3. Download packwiz-installer-bootstrap.jar
#   4. Create a fully configured PolyMC instance for NeoForge 1.21.1,
#      directly inside PolyMC's real "instances" directory
#   5. Configure packwiz bootstrap so mods sync automatically on launch

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACK_NAME="Minecraft Infra Pack 1.21.1 (NeoForge)"
INSTANCE_DIRNAME="minecraft-infra-pack"
PACKWIZ_BOOTSTRAP_URL="https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
PACKWIZ_PACK_URL="https://raw.githubusercontent.com/Le0nRoy/minecraft_server/main/packwiz/pack.toml"
MC_VERSION="1.21.1"
NEOFORGE_VERSION="21.1.244"
LWJGL_VERSION="3.3.3"
POLYMC_RELEASES_API_URL="https://api.github.com/repos/PolyMC/PolyMC/releases/latest"
ADOPTIUM_API_URL="https://api.adoptium.net/v3/assets/feature_releases/21/ga?image_type=jdk&architecture=x64&vendor=eclipse&page_size=1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Step 1 - Locate (or offer to install) PolyMC
# ---------------------------------------------------------------------------

find_polymc_app() {
    local candidates=(
        "${HOME}/Applications/PolyMC.app"
        "/Applications/PolyMC.app"
    )

    for app in "${candidates[@]}"; do
        if [[ -d "${app}" ]]; then
            echo "${app}"
            return 0
        fi
    done

    return 1
}

get_polymc_dmg_url() {
    local api_response asset_url
    api_response="$(curl -fsSL "${POLYMC_RELEASES_API_URL}")"
    asset_url="$(echo "${api_response}" | grep -o '"browser_download_url": *"[^"]*\.dmg"' | head -1 | grep -o 'https://[^"]*')"
    echo "${asset_url}"
}

offer_install_polymc() {
    local tmp_dir="$1"

    echo ""
    warn "PolyMC is not installed in ~/Applications or /Applications."
    echo "  PolyMC supports offline (no Microsoft account) play out of the box."
    echo ""

    # Try Homebrew first if available
    if command -v brew &>/dev/null; then
        info "Homebrew detected — trying 'brew install --cask polymc'..."
        if brew install --cask polymc; then
            success "PolyMC installed via Homebrew."
            return 0
        fi
        warn "Homebrew cask install failed — falling back to direct DMG download."
        echo ""
    fi

    read -r -p "  Download and install PolyMC from the release binary now? [Y/n] " answer
    if [[ "${answer,,}" == "n" ]]; then
        echo ""
        echo "  Download manually from: https://github.com/PolyMC/PolyMC/releases/latest"
        echo "  Copy PolyMC.app to ~/Applications, then re-run this script."
        exit 1
    fi

    info "Fetching latest PolyMC release info..."
    local dmg_url
    dmg_url="$(get_polymc_dmg_url)" || true

    if [[ -z "${dmg_url}" ]]; then
        warn "Could not resolve latest PolyMC DMG URL automatically."
        echo "  Download manually from: https://github.com/PolyMC/PolyMC/releases/latest"
        echo "  Copy PolyMC.app to ~/Applications, then re-run this script."
        exit 1
    fi

    # Use the caller's tmp_dir so the existing EXIT trap handles cleanup on error
    local tmp_dmg="${tmp_dir}/PolyMC.dmg"
    info "Downloading PolyMC DMG..."
    curl -fsSL --progress-bar -o "${tmp_dmg}" "${dmg_url}"

    info "Mounting DMG..."
    local mount_point
    mount_point="$(hdiutil attach "${tmp_dmg}" -nobrowse -readonly | awk 'END{print $NF}')"

    info "Copying PolyMC.app to ~/Applications..."
    mkdir -p "${HOME}/Applications"
    cp -R "${mount_point}/PolyMC.app" "${HOME}/Applications/"

    info "Unmounting DMG..."
    hdiutil detach "${mount_point}" -quiet

    success "PolyMC installed to ~/Applications/PolyMC.app"
}

# ---------------------------------------------------------------------------
# Step 2 - Locate PolyMC's real "instances" directory
# ---------------------------------------------------------------------------

find_polymc_data_dir() {
    local app_path="$1"

    # Portable installs keep their data (including instances/) right next to
    # the .app bundle, marked by a polymc.cfg file there.
    local app_parent
    app_parent="$(dirname "${app_path}")"
    if [[ -f "${app_parent}/polymc.cfg" ]]; then
        echo "${app_parent}"
        return 0
    fi

    # Installed (non-portable) PolyMC keeps user data under
    # ~/Library/Application Support, standard for macOS apps.
    local standard="${HOME}/Library/Application Support/PolyMC"
    echo "${standard}"
    return 0
}

# ---------------------------------------------------------------------------
# Step 3 - Check / auto-install Java 21+
# ---------------------------------------------------------------------------

get_java_major() {
    local java_bin="java"
    if /usr/libexec/java_home -v 21 &>/dev/null 2>&1; then
        java_bin="$(/usr/libexec/java_home -v 21)/bin/java"
    fi
    local version_output major
    version_output="$("${java_bin}" -version 2>&1 | head -1)"
    major="$(echo "${version_output}" | grep -oE '"([0-9]+)' | grep -oE '[0-9]+' | head -1)"
    echo "${major}"
}

install_java() {
    echo ""
    warn "Java 21+ is required but was not found (or is too old)."
    echo ""

    info "Looking up the latest Java 21 (Temurin) installer..."
    local pkg_url
    pkg_url="$(curl -fsSL "${ADOPTIUM_API_URL}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['binaries'][0]['installer']['link'])" 2>/dev/null || true)"

    if [[ -z "${pkg_url}" ]]; then
        warn "Could not resolve the latest Java 21 installer automatically."
        echo "  Install manually from: https://adoptium.net/temurin/releases/?version=21"
        open "https://adoptium.net/temurin/releases/?version=21" 2>/dev/null || true
        return 1
    fi

    local tmp_pkg
    tmp_pkg="$(mktemp -t temurin21).pkg"
    info "Downloading Java 21 installer..."
    curl -fsSL --progress-bar -o "${tmp_pkg}" "${pkg_url}"

    info "Installing Java 21 (requires sudo)..."
    sudo installer -pkg "${tmp_pkg}" -target /
    local result=$?
    rm -f "${tmp_pkg}"
    return ${result}
}

check_java() {
    local major
    major="$(get_java_major)"

    if [[ -n "${major}" ]] && (( major >= 21 )); then
        success "Java ${major} detected."
        return 0
    fi

    if [[ -n "${major}" ]]; then
        warn "Java ${major} detected, but Minecraft ${MC_VERSION} requires Java 21 or newer."
    else
        warn "Java 21+ is not installed."
    fi

    if ! install_java; then
        die "Please install Java 21+ manually and re-run."
    fi

    major="$(get_java_major)"
    if [[ -n "${major}" ]] && (( major >= 21 )); then
        success "Java ${major} installed and detected."
    else
        warn "Java was installed but version could not be confirmed as 21+ in this session - open a new terminal and re-run if the instance fails to launch."
    fi
}

# ---------------------------------------------------------------------------
# Step 4 - Download packwiz-installer-bootstrap.jar
# ---------------------------------------------------------------------------

download_bootstrap() {
    local dest="$1"
    if [[ -f "${dest}" ]]; then
        success "packwiz-installer-bootstrap.jar already present."
        return 0
    fi

    info "Downloading packwiz-installer-bootstrap.jar..."
    if command -v curl &>/dev/null; then
        curl -fsSL --progress-bar -o "${dest}" "${PACKWIZ_BOOTSTRAP_URL}"
    else
        die "curl is required but not found. Install Xcode Command Line Tools: xcode-select --install"
    fi
    success "Downloaded packwiz-installer-bootstrap.jar."
}

# ---------------------------------------------------------------------------
# Step 5 - Create PolyMC instance
# ---------------------------------------------------------------------------

create_instance() {
    local base_dir="$1"
    local bootstrap_jar="$2"
    local instance_dir="${base_dir}/${INSTANCE_DIRNAME}"

    if [[ -d "${instance_dir}" ]]; then
        warn "Instance directory already exists: ${instance_dir}"
        read -r -p "  Overwrite existing instance? [y/N] " answer
        if [[ "${answer,,}" != "y" ]]; then
            info "Keeping existing instance. Exiting."
            exit 0
        fi
        info "Removing existing instance directory..."
        rm -rf "${instance_dir}"
    fi

    info "Creating instance directory: ${instance_dir}"
    mkdir -p "${instance_dir}/.minecraft"

    # --- instance.cfg ---
    info "Writing instance.cfg..."
    cat > "${instance_dir}/instance.cfg" <<EOF
InstanceType=OneSix
IntendedVersion=${MC_VERSION}
LogPrePostOutput=true
MaxMemAlloc=4096
MinMemAlloc=1024
OverrideJavaArgs=true
JvmArgs=-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200
OverrideCommands=true
PreLaunchCommand="\$INST_JAVA" -jar packwiz-installer-bootstrap.jar ${PACKWIZ_PACK_URL}
iconKey=default
name=${PACK_NAME}
EOF

    # --- mmc-pack.json ---
    info "Writing mmc-pack.json..."
    cat > "${instance_dir}/mmc-pack.json" <<EOF
{
  "components": [
    {"cachedName": "LWJGL 3", "dependencyOnly": true, "uid": "org.lwjgl3", "version": "${LWJGL_VERSION}"},
    {"cachedName": "Minecraft", "important": true, "uid": "net.minecraft", "version": "${MC_VERSION}"},
    {"cachedName": "NeoForge", "uid": "net.neoforged", "version": "${NEOFORGE_VERSION}"}
  ],
  "formatVersion": 1
}
EOF

    # --- Copy bootstrap jar into .minecraft ---
    # Must live here: PolyMC runs PreLaunchCommand with the instance's
    # .minecraft directory as its working directory, and the command
    # above references the jar by relative path.
    info "Copying packwiz-installer-bootstrap.jar into instance..."
    cp "${bootstrap_jar}" "${instance_dir}/.minecraft/packwiz-installer-bootstrap.jar"

    success "Instance created at: ${instance_dir}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo ""
    echo "==========================================="
    echo "  Minecraft Infra Pack - macOS Installer   "
    echo "==========================================="
    echo ""

    # Scratch directory for downloads
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp_dir}'" EXIT

    local bootstrap_jar="${tmp_dir}/packwiz-installer-bootstrap.jar"

    # 1. Locate (or install) PolyMC
    info "Locating PolyMC..."
    local polymc_app
    if ! polymc_app="$(find_polymc_app)"; then
        offer_install_polymc "${tmp_dir}"
        if ! polymc_app="$(find_polymc_app)"; then
            die "Could not locate PolyMC after installation. Run it once manually, then re-run this script."
        fi
    fi
    success "Found PolyMC: ${polymc_app}"

    # 2. Locate its real instances directory
    info "Locating PolyMC's instances directory..."
    local polymc_data_dir instances_dir
    polymc_data_dir="$(find_polymc_data_dir "${polymc_app}")"
    instances_dir="${polymc_data_dir}/instances"
    mkdir -p "${instances_dir}"
    success "Instances directory: ${instances_dir}"

    # 3. Java
    check_java

    # 4. Download bootstrap
    download_bootstrap "${bootstrap_jar}"

    # 5. Create instance directly inside PolyMC's instances directory
    create_instance "${instances_dir}" "${bootstrap_jar}"

    # ---------------------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------------------

    echo ""
    echo "==========================================="
    echo -e "  ${GREEN}Installation complete!${NC}                 "
    echo "==========================================="
    echo ""
    echo "  The instance was created directly inside PolyMC's instances"
    echo "  folder - no manual copying needed."
    echo ""
    echo "  Next steps:"
    echo "  1. Open (or restart) PolyMC."
    echo "  2. Add an offline account: Accounts (top-right) → Add Offline → enter any username."
    echo "  3. Find and select '${PACK_NAME}'."
    echo "  4. Click Launch - packwiz will download all mods on first run."
    echo "  5. Connect to the server — no Microsoft account required."
    echo ""
    echo "  Tip: An internet connection is required on first launch."
    echo ""

    # Show a native macOS notification
    osascript -e "display notification \"Instance ready - launch PolyMC to play!\" with title \"Minecraft Infra Pack\" subtitle \"Installation complete\"" 2>/dev/null || true
}

main "$@"
