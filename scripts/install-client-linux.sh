#!/usr/bin/env bash
# install-client-linux.sh — Install the Minecraft Infra Pack modpack on Linux via Prism Launcher.
#
# Usage: bash install-client-linux.sh
#
# Environment overrides:
#   PRISM_LAUNCHER_DIR   — Override auto-detection of Prism Launcher data directory
#
# The script will:
#   1. Locate (or offer to install) Prism Launcher
#   2. Verify Java 17+ is available
#   3. Download packwiz-installer-bootstrap.jar
#   4. Create a fully configured Prism Launcher instance for Fabric 1.20.1
#   5. Configure packwiz bootstrap so mods sync automatically on launch

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACK_NAME="Minecraft Infra Pack 1.20.1"
INSTANCE_DIRNAME="minecraft-infra-pack"
PACKWIZ_BOOTSTRAP_URL="https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
PACKWIZ_PACK_URL="https://raw.githubusercontent.com/YOUR_ORG/minecraft-infra/main/packwiz/pack.toml"
MC_VERSION="1.20.1"
FABRIC_VERSION="0.15.11"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'  # No colour

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

require_cmd() {
    command -v "$1" &>/dev/null || die "Required command not found: $1  Please install it and re-run."
}

# ---------------------------------------------------------------------------
# Step 1 — Locate Prism Launcher data directory
# ---------------------------------------------------------------------------

find_prism_dir() {
    # Priority 1: environment override
    if [[ -n "${PRISM_LAUNCHER_DIR:-}" ]]; then
        if [[ -d "${PRISM_LAUNCHER_DIR}" ]]; then
            echo "${PRISM_LAUNCHER_DIR}"
            return 0
        else
            warn "PRISM_LAUNCHER_DIR is set to '${PRISM_LAUNCHER_DIR}' but the directory does not exist."
            warn "Falling through to auto-detection."
        fi
    fi

    # Priority 2: native install
    local native="${HOME}/.local/share/PrismLauncher"
    if [[ -d "${native}" ]]; then
        echo "${native}"
        return 0
    fi

    # Priority 3: Flatpak
    local flatpak="${HOME}/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher"
    if [[ -d "${flatpak}" ]]; then
        echo "${flatpak}"
        return 0
    fi

    # Priority 4: Snap
    local snap="${HOME}/snap/prismlauncher/current/.local/share/PrismLauncher"
    if [[ -d "${snap}" ]]; then
        echo "${snap}"
        return 0
    fi

    return 1
}

offer_install_prism() {
    echo ""
    warn "Prism Launcher does not appear to be installed."
    echo "  This installer requires Prism Launcher to manage the modpack instance."
    echo ""

    if command -v flatpak &>/dev/null; then
        echo "  [flatpak detected]"
        read -r -p "  Install Prism Launcher via Flatpak now? [y/N] " answer
        if [[ "${answer,,}" == "y" ]]; then
            info "Installing Prism Launcher via Flatpak..."
            flatpak install --user -y flathub org.prismlauncher.PrismLauncher
            # Initialise data directory by launching once, then quitting
            info "Launching Prism Launcher briefly to initialise its data directory..."
            flatpak run org.prismlauncher.PrismLauncher &
            local pid=$!
            sleep 6
            kill "${pid}" 2>/dev/null || true
            wait "${pid}" 2>/dev/null || true
            return 0
        fi
    elif command -v snap &>/dev/null; then
        echo "  [snap detected]"
        read -r -p "  Install Prism Launcher via Snap now? [y/N] " answer
        if [[ "${answer,,}" == "y" ]]; then
            info "Installing Prism Launcher via Snap..."
            sudo snap install prismlauncher
            info "Launching Prism Launcher briefly to initialise its data directory..."
            snap run prismlauncher &
            local pid=$!
            sleep 6
            kill "${pid}" 2>/dev/null || true
            wait "${pid}" 2>/dev/null || true
            return 0
        fi
    fi

    echo ""
    echo "  Please install Prism Launcher manually:"
    echo "    https://prismlauncher.org/download/linux"
    echo ""
    echo "  Run this script again after installation."
    exit 1
}

# ---------------------------------------------------------------------------
# Step 2 — Check Java 17+
# ---------------------------------------------------------------------------

check_java() {
    if ! command -v java &>/dev/null; then
        warn "Java is not installed or not on PATH."
        echo "  Minecraft ${MC_VERSION} requires Java 17 or newer."
        echo "  Install it from your package manager, for example:"
        echo "    sudo apt install openjdk-17-jre       (Debian/Ubuntu)"
        echo "    sudo dnf install java-17-openjdk      (Fedora/RHEL)"
        echo "    sudo pacman -S jre17-openjdk           (Arch)"
        echo "    flatpak install flathub org.freedesktop.Sdk.Extension.openjdk17"
        die "Please install Java 17+ and re-run."
    fi

    local version_output
    version_output="$(java -version 2>&1 | head -1)"
    # Parse major version from strings like: openjdk version "17.0.9" or "1.8.0_xxx"
    local major
    major="$(echo "${version_output}" | grep -oP '(?<=version ")(1\.\K[0-9]+|[0-9]+)(?=[\."_])' | head -1)"

    if [[ -z "${major}" ]]; then
        warn "Could not determine Java version from: ${version_output}"
        warn "Proceeding anyway — ensure Java 17+ is available."
        return 0
    fi

    if (( major < 17 )); then
        die "Java ${major} detected, but Minecraft ${MC_VERSION} requires Java 17 or newer. Please upgrade."
    fi

    success "Java ${major} detected."
}

# ---------------------------------------------------------------------------
# Step 3 — Download packwiz-installer-bootstrap.jar
# ---------------------------------------------------------------------------

download_bootstrap() {
    local dest="$1"
    if [[ -f "${dest}" ]]; then
        success "packwiz-installer-bootstrap.jar already present at ${dest}"
        return 0
    fi

    info "Downloading packwiz-installer-bootstrap.jar..."
    if command -v curl &>/dev/null; then
        curl -fsSL --progress-bar -o "${dest}" "${PACKWIZ_BOOTSTRAP_URL}"
    elif command -v wget &>/dev/null; then
        wget -q --show-progress -O "${dest}" "${PACKWIZ_BOOTSTRAP_URL}"
    else
        die "Neither curl nor wget found. Please install one and re-run."
    fi
    success "Downloaded packwiz-installer-bootstrap.jar"
}

# ---------------------------------------------------------------------------
# Step 4 — Create Prism Launcher instance
# ---------------------------------------------------------------------------

create_instance() {
    local prism_dir="$1"
    local bootstrap_jar="$2"
    local instance_dir="${prism_dir}/instances/${INSTANCE_DIRNAME}"

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
iconKey=default
name=${PACK_NAME}
PreLaunchCommand="\$INST_JAVA" -jar packwiz-installer-bootstrap.jar ${PACKWIZ_PACK_URL}
EOF

    # --- mmc-pack.json ---
    info "Writing mmc-pack.json..."
    cat > "${instance_dir}/mmc-pack.json" <<'EOF'
{
  "components": [
    {"cachedName": "LWJGL 3", "dependencyOnly": true, "uid": "org.lwjgl3", "version": "3.3.1"},
    {"cachedName": "Minecraft", "uid": "net.minecraft", "version": "1.20.1"},
    {"cachedName": "Fabric Loader", "uid": "net.fabricmc.fabric-loader", "version": "0.15.11"}
  ],
  "formatVersion": 1
}
EOF

    # --- Copy bootstrap jar into the instance root ---
    info "Copying packwiz-installer-bootstrap.jar into instance..."
    cp "${bootstrap_jar}" "${instance_dir}/packwiz-installer-bootstrap.jar"

    success "Instance created at: ${instance_dir}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo ""
    echo "=========================================="
    echo "  Minecraft Infra Pack — Linux Installer  "
    echo "=========================================="
    echo ""

    # Scratch directory for downloaded assets
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp_dir}'" EXIT

    local bootstrap_jar="${tmp_dir}/packwiz-installer-bootstrap.jar"

    # 1. Locate Prism Launcher
    info "Locating Prism Launcher data directory..."
    local prism_dir
    if ! prism_dir="$(find_prism_dir)"; then
        offer_install_prism
        # Try again after installation
        if ! prism_dir="$(find_prism_dir)"; then
            die "Could not locate Prism Launcher data directory even after installation attempt. Run the launcher once manually, then re-run this script."
        fi
    fi
    success "Found Prism Launcher data directory: ${prism_dir}"

    # 2. Check Java
    info "Checking Java version..."
    check_java

    # 3. Download bootstrap
    download_bootstrap "${bootstrap_jar}"

    # 4. Create instance
    create_instance "${prism_dir}" "${bootstrap_jar}"

    # ---------------------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------------------

    echo ""
    echo "=========================================="
    echo -e "  ${GREEN}Installation complete!${NC}                "
    echo "=========================================="
    echo ""
    echo "  Next steps:"
    echo "  1. Open Prism Launcher."
    echo "  2. Find the instance named '${PACK_NAME}'."
    echo "  3. Click Launch — packwiz will automatically download all mods on first run."
    echo "  4. Enjoy the server!"
    echo ""
    echo "  Note: An internet connection is required on first launch so packwiz"
    echo "        can fetch all mod files."
    echo ""
}

main "$@"
