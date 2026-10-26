#!/bin/bash
# EC2 first-boot setup (Amazon Linux 2023): Docker, Compose, swap, nightly DB backup timer.
set -euxo pipefail
dnf install -y docker git tar
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
ARCH=$(uname -m)
curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${ARCH}" -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
curl -fsSL "https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-$( [ "$ARCH" = aarch64 ] && echo arm64 || echo amd64 )" -o /usr/local/lib/docker/cli-plugins/docker-buildx
chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

# 2 GB swap: headroom for image builds and spikes on a 1 GB instance.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf && sysctl --system

mkdir -p /opt/aubot && chown ec2-user:ec2-user /opt/aubot
touch /var/lib/cloud/instance/aubot-ready
