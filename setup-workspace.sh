#!/usr/bin/env bash
# Recreates what the iximiuz playground pre-initializes in the laborant's HOME:
# the sources/ and nginx/ directories. No root required. Safe to re-run.
# Mirrors the `init_unikraft_nginx` task from the tutorial's front matter.
set -euo pipefail

LAB="$(cd "$(dirname "$0")" && pwd)/lab"
mkdir -p "$LAB"
cd "$LAB"

declare -A sources=(
	[unikraft]=unikraft::f6f00b2d
	[libs/musl]=lib-musl::RELEASE-0.21.0
	[libs/lwip]=lib-lwip::RELEASE-0.21.0
	[libs/nginx]=lib-nginx::RELEASE-0.18.0
)

for s in "${!sources[@]}"; do
	test -d sources/"$s" || git clone https://github.com/unikraft/"${sources[$s]%%::*}" sources/"$s"
	git -C sources/"$s" reset --hard "${sources[$s]##*::}"
done

if test -d nginx/.git; then
	echo "nginx/ workspace already exists, leaving it alone"
	exit 0
fi

git init nginx
cd nginx

catalog="$(mktemp -d)"
trap 'rm -rf "$catalog"' EXIT
git clone https://github.com/unikraft/catalog-core.git "$catalog"/catalog-core
git -C "$catalog"/catalog-core reset --hard 44f4e89
mv "$catalog"/catalog-core/nginx/{rootfs,Makefile,Makefile.uk} .

cat <<'EOF' >Config.uk
config APPNGINX
bool "Configure Nginx application with initrd as rootfs"
default y

	# Select the application library (Nginx).
	# Use the main function from the application library.
	select LIBNGINX
	select LIBNGINX_MAIN_FUNCTION

	# Select filesystem core components: posix-vfs, cpio.
	# Other libraries (musl, lwIP) and core components are selected as dependencies of LIBNGINX.
	select LIBPOSIX_VFS
	select LIBUKCPIO

	# Use extended information (einfo) for configuring network parameters.
	# This component parses the configuration string in the command line:
	#    netdev.ip=172.17.0.2/24:172.17.0.1:::
	select LIBUKNETDEV_EINFO_LIBPARAM
EOF

cat <<'EOF' >qemu-x86_64.defconfig
CONFIG_PLAT_KVM=y
CONFIG_LIBUKPRINT_KLVL_INFO=y
CONFIG_LIBUKFS_DEVFS=y
CONFIG_LIBPOSIX_VFS_FSTAB=y
CONFIG_LIBPOSIX_VFS_FSTAB_BUILTIN=y
CONFIG_LIBPOSIX_VFS_FSTAB_BUILTIN_EINITRD=y
EOF

mkdir -p workdir/libs
for s in "${!sources[@]}"; do
	ln -srTf ../sources/"$s" workdir/"$s"
done

mkdir workdir/build
cat <<'EOF' >workdir/build/.gitignore
/*
!/.gitignore
!/nginx_*
EOF

mkdir oci
cat <<'EOF' >oci/bunnyfile
#syntax=harbor.nbfc.io/nubificus/bunny:latest
version: v0.1

platforms:
  framework: unikraft
  version: 0.21.0
  monitor: qemu
  architecture: x86

kernel:
  from: local
  path: nginx_qemu-x86_64

cmd: ['-c', '/nginx/conf/nginx.conf']
EOF

sed -i -e 's/\(Hello from \)Unikraft/\1iximiuz Labs/g' rootfs/nginx/html/index.html

git add --all
git -c commit.gpgsign=false commit --quiet -m 'Lab init'

echo
echo "Workspace ready: $LAB"
