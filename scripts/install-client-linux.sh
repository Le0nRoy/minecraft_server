#!/usr/bin/env bash
# install-client-linux.sh - Install the Minecraft Infra Pack modpack on Linux via Prism Launcher.
#
# Usage: bash install-client-linux.sh
#
# Environment overrides:
#   PRISM_LAUNCHER_DIR - Override auto-detection of Prism Launcher data directory
#
# The script will:
#   1. Locate (or offer to install) Prism Launcher
#   2. Verify (or offer to install) Java 21+
#   3. Download packwiz-installer-bootstrap.jar
#   4. Create a fully configured Prism Launcher instance for NeoForge 1.21.1,
#      directly inside Prism's real "instances" directory
#   5. Configure packwiz bootstrap so mods sync automatically on launch

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACK_NAME="Minecraft Infra Pack 1.21.1 (NeoForge)"
INSTANCE_DIRNAME="minecraft-infra-pack"
PACKWIZ_BOOTSTRAP_URL="https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
PACKWIZ_PACK_URL="https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/packwiz/pack.toml"
MC_VERSION="1.21.1"
NEOFORGE_VERSION="21.1.244"
LWJGL_VERSION="3.3.3"

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
# Step 1 - Locate Prism Launcher data directory
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
# Step 2 - Check / auto-install Java 21+
# ---------------------------------------------------------------------------

get_java_major() {
    local version_output major
    version_output="$(java -version 2>&1 | head -1)"
    # Parse major version from strings like: openjdk version "21.0.7" or "1.8.0_xxx"
    major="$(echo "${version_output}" | grep -oP '(?<=version ")(1\.\K[0-9]+|[0-9]+)(?=[\."_])' | head -1)"
    echo "${major}"
}

install_java() {
    echo ""
    warn "Java 21+ is required but was not found (or is too old)."
    echo ""

    local answer
    if command -v apt &>/dev/null; then
        read -r -p "  Install openjdk-21-jre now via apt (needs sudo)? [Y/n] " answer
        if [[ "${answer,,}" != "n" ]]; then
            info "Installing openjdk-21-jre via apt..."
            sudo apt update && sudo apt install -y openjdk-21-jre
            return $?
        fi
    elif command -v dnf &>/dev/null; then
        read -r -p "  Install java-21-openjdk now via dnf (needs sudo)? [Y/n] " answer
        if [[ "${answer,,}" != "n" ]]; then
            info "Installing java-21-openjdk via dnf..."
            sudo dnf install -y java-21-openjdk
            return $?
        fi
    elif command -v pacman &>/dev/null; then
        read -r -p "  Install jre21-openjdk now via pacman (needs sudo)? [Y/n] " answer
        if [[ "${answer,,}" != "n" ]]; then
            info "Installing jre21-openjdk via pacman..."
            sudo pacman -S --noconfirm jre21-openjdk
            return $?
        fi
    elif command -v flatpak &>/dev/null; then
        read -r -p "  Install the Java 21 Flatpak SDK extension now? [Y/n] " answer
        if [[ "${answer,,}" != "n" ]]; then
            info "Installing Java 21 via Flatpak..."
            flatpak install --user -y flathub org.freedesktop.Sdk.Extension.openjdk21
            return $?
        fi
    fi

    echo ""
    echo "  Install Java 21+ manually, for example:"
    echo "    sudo apt install openjdk-21-jre       (Debian/Ubuntu)"
    echo "    sudo dnf install java-21-openjdk      (Fedora/RHEL)"
    echo "    sudo pacman -S jre21-openjdk           (Arch)"
    echo "    flatpak install flathub org.freedesktop.Sdk.Extension.openjdk21"
    return 1
}

check_java() {
    if ! command -v java &>/dev/null; then
        if ! install_java; then
            die "Please install Java 21+ and re-run."
        fi
    else
        local major
        major="$(get_java_major)"
        if [[ -z "${major}" ]]; then
            warn "Could not determine Java version from 'java -version' output."
            warn "Proceeding anyway - ensure Java 21+ is available."
            return 0
        fi
        if (( major < 21 )); then
            warn "Java ${major} detected, but Minecraft ${MC_VERSION} requires Java 21 or newer."
            if ! install_java; then
                die "Please upgrade to Java 21+ and re-run."
            fi
        else
            success "Java ${major} detected."
            return 0
        fi
    fi

    # Re-check after an install attempt
    if ! command -v java &>/dev/null; then
        die "Java still not found on PATH after installation. Open a new terminal and re-run, or install manually."
    fi
    local major
    major="$(get_java_major)"
    if [[ -n "${major}" ]] && (( major >= 21 )); then
        success "Java ${major} installed and detected."
    else
        warn "Java was installed but version could not be confirmed as 21+ in this session - open a new terminal and re-run if the instance fails to launch."
    fi
}

# ---------------------------------------------------------------------------
# Step 3 - Download packwiz-installer-bootstrap.jar
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
# Step 4 - Create Prism Launcher instance
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
    # Must live here: Prism runs PreLaunchCommand with the instance's
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
    echo "=========================================="
    echo "  Minecraft Infra Pack - Linux Installer  "
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
    echo "  3. Click Launch - packwiz will automatically download all mods on first run."
    echo "  4. Enjoy the server!"
    echo ""
    echo "  Note: An internet connection is required on first launch so packwiz"
    echo "        can fetch all mod files."
    echo ""
}

main "$@"
