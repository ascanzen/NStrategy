#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "Please run with sudo: sudo bash scripts/install_docker_aliyun.sh"
  fi
}

install_debian_family() {
  local id="$1"
  local codename="${VERSION_CODENAME:-}"
  if [[ -z "$codename" ]]; then
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
  fi
  [[ -n "$codename" ]] || die "Cannot detect Debian/Ubuntu codename."

  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings

  curl -fsSL "https://mirrors.aliyun.com/docker-ce/linux/${id}/gpg" \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/${id} ${codename} stable
EOF

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

install_rhel_family() {
  local package_manager="yum"
  if command -v dnf >/dev/null 2>&1; then
    package_manager="dnf"
  fi

  "$package_manager" install -y yum-utils ca-certificates curl
  yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
  "$package_manager" install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

configure_docker_daemon() {
  mkdir -p /etc/docker

  if [[ -n "${ALIYUN_DOCKER_MIRROR:-}" ]]; then
    cat >/etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["${ALIYUN_DOCKER_MIRROR}"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF
  elif [[ ! -f /etc/docker/daemon.json ]]; then
    cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF
  fi
}

enable_docker() {
  systemctl daemon-reload
  systemctl enable --now docker
  docker version
  docker compose version
}

add_user_to_group() {
  local user_name="${SUDO_USER:-}"
  if [[ -n "$user_name" && "$user_name" != "root" ]]; then
    usermod -aG docker "$user_name"
    echo "Added ${user_name} to docker group. Re-login or run: newgrp docker"
  fi
}

main() {
  need_root
  [[ -f /etc/os-release ]] || die "/etc/os-release not found."
  # shellcheck disable=SC1091
  source /etc/os-release

  case "${ID:-}" in
    ubuntu|debian)
      install_debian_family "$ID"
      ;;
    centos|rhel|rocky|almalinux|alinux|anolis)
      install_rhel_family
      ;;
    *)
      case "${ID_LIKE:-}" in
        *debian*)
          install_debian_family "debian"
          ;;
        *rhel*|*fedora*)
          install_rhel_family
          ;;
        *)
          die "Unsupported Linux distribution: ${PRETTY_NAME:-unknown}"
          ;;
      esac
      ;;
  esac

  configure_docker_daemon
  enable_docker
  add_user_to_group
  echo "Docker installation completed with Aliyun Docker CE repository."
}

main "$@"
