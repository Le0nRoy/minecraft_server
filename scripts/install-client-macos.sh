#!/usr/bin/env bash
# install-client-macos.sh — Install the Minecraft Infra Pack modpack on macOS via Prism Launcher.
#
# Usage: bash install-client-macos.sh
#
# The script will:
#   1. Present a native macOS folder picker to choose install location
#   2. Locate Prism Launcher in ~/Applications or /Applications
#   3. Verify Java 21+ is available
#   4. Download packwiz-installer-bootstrap.jar
#   5. Create a fully configured Prism Launcher instance for NeoForge 1.21.1
#   6. Configure packwiz bootstrap so mods sync automatically on launch

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
PRISM_DOWNLOAD_URL="https://prismlauncher.org/download/mac"

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
# Step 1 — Native folder picker via osascript
# ---------------------------------------------------------------------------

pick_directory() {
    local prompt="$1"
    # osascript returns a POSIX path like /Users/alice/Documents
    local result
    result="$(osascript -e "choose folder with prompt \"${prompt}\"" 2>/dev/null)" || return 1

    # osascript returns HFS path (e.g. "Macintosh HD:Users:alice") on older macOS
    # Modern macOS (10.15+) returns POSIX paths; convert either form.
    if [[ "${result}" == *:* ]]; then
        # HFS path — convert via Python
        result="$(python3 -c "import sys; p=sys.argv[1]; print('/' + p.replace(':','/').lstrip('/').replace('Macintosh HD/','',1))" "${result}")"
    fi

    echo "${result}"
}

# ---------------------------------------------------------------------------
# Step 2 — Locate Prism Launcher
# ---------------------------------------------------------------------------

find_prism_app() {
    local candidates=(
        "${HOME}/Applications/Prism Launcher.app"
        "/Applications/Prism Launcher.app"
    )

    for app in "${candidates[@]}"; do
        if [[ -d "${app}" ]]; then
            echo "${app}"
            return 0
        fi
    done

    return 1
}

offer_install_prism() {
    echo ""
    warn "Prism Launcher is not installed in ~/Applications or /Applications."
    echo ""
    read -r -p "  Open the Prism Launcher download page in your browser? [Y/n] " answer
    if [[ "${answer,,}" != "n" ]]; then
        open "${PRISM_DOWNLOAD_URL}"
        echo ""
        echo "  Please install Prism Launcher, run it once, and then re-run this script."
    else
        echo ""
        echo "  Download Prism Launcher manually from: ${PRISM_DOWNLOAD_URL}"
        echo "  Run this script again after installation."
    fi
    exit 1
}

# ---------------------------------------------------------------------------
# Step 3 — Check Java 21+
# ---------------------------------------------------------------------------

check_java() {
    # macOS ships with a java stub that prompts to install JDK; we skip that
    if ! /usr/libexec/java_home -v 21 &>/dev/null 2>&1; then
        # Fallback: check $PATH
        if ! command -v java &>/dev/null; then
            warn "Java 21+ is not installed."
            echo "  Minecraft ${MC_VERSION} requires Java 21 or newer."
            echo ""
            echo "  Install options:"
            echo "    1. Homebrew:    brew install --cask temurin@21"
            echo "    2. Download:    https://adoptium.net/temurin/releases/?version=21"
            echo ""
            read -r -p "  Open the download page now? [Y/n] " answer
            if [[ "${answer,,}" != "n" ]]; then
                open "https://adoptium.net/temurin/releases/?version=21"
            fi
            die "Please install Java 21+ and re-run."
        fi
    fi

    # Use JAVA_HOME from java_home helper if available
    local java_bin="java"
    if /usr/libexec/java_home -v 21 &>/dev/null 2>&1; then
        java_bin="$(/usr/libexec/java_home -v 21)/bin/java"
    fi

    local version_output
    version_output="$("${java_bin}" -version 2>&1 | head -1)"
    local major
    major="$(echo "${version_output}" | grep -oE '"([0-9]+)' | grep -oE '[0-9]+' | head -1)"

    if [[ -z "${major}" ]]; then
        warn "Could not parse Java version from: ${version_output}"
        warn "Proceeding anyway — ensure Java 21+ is configured in Prism Launcher."
        return 0
    fi

    if (( major < 21 )); then
        die "Java ${major} detected, but Minecraft ${MC_VERSION} requires Java 21 or newer."
    fi

    success "Java ${major} detected."
}

# ---------------------------------------------------------------------------
# Step 4 — Download packwiz-installer-bootstrap.jar
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
# Step 5 — Create Prism Launcher instance
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
    echo "==========================================="
    echo "  Minecraft Infra Pack — macOS Installer   "
    echo "==========================================="
    echo ""

    # Scratch directory for downloads
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp_dir}'" EXIT

    local bootstrap_jar="${tmp_dir}/packwiz-installer-bootstrap.jar"

    # 1. Folder picker
    info "Opening folder picker — choose where to install the instance..."
    local install_dir
    if ! install_dir="$(pick_directory "Select where to install the Minecraft Infra Pack instance")"; then
        warn "No folder selected. Installation cancelled."
        exit 0
    fi
    success "Install directory: ${install_dir}"

    # 2. Prism Launcher
    info "Locating Prism Launcher..."
    local prism_app
    if ! prism_app="$(find_prism_app)"; then
        offer_install_prism
    fi
    success "Found Prism Launcher: ${prism_app}"

    # If the user chose a directory that looks like the Prism instances folder
    # (i.e. it ends with /instances), use it directly; otherwise put the instance
    # inside the chosen directory.
    local effective_base="${install_dir}"

    # 3. Java
    info "Checking Java version..."
    check_java

    # 4. Download bootstrap
    download_bootstrap "${bootstrap_jar}"

    # 5. Create instance
    create_instance "${effective_base}" "${bootstrap_jar}"

    # ---------------------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------------------

    echo ""
    echo "==========================================="
    echo -e "  ${GREEN}Installation complete!${NC}                 "
    echo "==========================================="
    echo ""
    echo "  Next steps:"
    echo "  1. Open Prism Launcher."
    echo "  2. If the instance does not appear automatically, click 'Add Instance'"
    echo "     and import the folder: ${effective_base}/${INSTANCE_DIRNAME}"
    echo "  3. Launch '${PACK_NAME}' — packwiz will download all mods on first run."
    echo "  4. Enjoy the server!"
    echo ""
    echo "  Tip: An internet connection is required on first launch."
    echo ""

    # Show a native macOS notification
    osascript -e "display notification \"Instance ready — launch Prism Launcher to play!\" with title \"Minecraft Infra Pack\" subtitle \"Installation complete\"" 2>/dev/null || true
}

main "$@"
