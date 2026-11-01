#!/bin/sh
# A throwaway primary + replica SeaweedFS for the archive integration tests,
# shaped like deploy/archive-storage: identities from s3.example.json and the
# admin command's new-writer, JWT keys from security.toml on both, a one-way
# sync that reads through the primary's filer, holds no key and never deletes,
# and only the S3 ports published (on loopback). As across the real link, the
# primary's volume server advertises an address the sync cannot reach: the
# primary sits on its own network and joins the link network beside it.
#
#   scripts/recording/archive-test-stack.sh up DIRECTORY   # writes DIRECTORY/archive-test.env
#   scripts/recording/archive-test-stack.sh down
#
# Every credential is random per run and lives only in DIRECTORY. PYTHON must
# have the gateway's requirements installed.
set -eu

IMAGE="chrislusf/seaweedfs@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d" # 4.48
NETWORK=ssf-archive-test
LINK=ssf-archive-test-link
PRIMARY_SUBNET=10.254.213.0/24
PRIMARY_ADDRESS=10.254.213.10
PRIMARY=ssf-archive-test-primary
REPLICA=ssf-archive-test-replica
SYNC=ssf-archive-test-sync
TENANT=tenant-ci
REPO=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}

down() {
    docker rm -f "$SYNC" "$PRIMARY" "$REPLICA" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" "$LINK" >/dev/null 2>&1 || true
}

random() { openssl rand -hex 16; }

wait_s3() {
    for _ in $(seq 90); do
        code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$1/" || true)
        [ "$code" = "403" ] && return 0
        sleep 1
    done
    echo "archive-test-stack.sh: S3 on port $1 did not come up" >&2
    exit 1
}

# s3.json for one site: the example's admin and retention identities with the
# given credentials, plus any new-writer outputs named after them.
identities() {
    out=$1; shift
    PYTHONPATH="$REPO" "$PYTHON" - "$REPO/deploy/archive-storage/s3.example.json" "$out" "$@" <<'EOF'
import json, sys
template, out, admin, retention, *writers = sys.argv[1:]
config = json.load(open(template))
for identity, pair in zip(config["identities"], (admin, retention)):
    key, secret = pair.split(":")
    identity["credentials"] = [{"accessKey": key, "secretKey": secret}]
for path in writers:
    writer = json.load(open(path))
    config["identities"].append(writer["seaweedfs_identity"])
    config["policies"].append(writer["seaweedfs_policy"])
json.dump(config, open(out, "w"))
EOF
}

# Object Lock lives in the S3 layer only; the filer and the volume server
# below it must refuse an unsigned write.
demand_jwt() {
    for target in 8888/buckets/probe 8080/3,01637037d6; do
        answer=$(docker exec "$1" sh -c "a=\$(hostname -i); wget -q -O- --post-data=x \"http://\${a%% *}:$target\" 2>&1" || true)
        case "$answer" in
            *"401 Unauthorized"*) ;;
            *) echo "archive-test-stack.sh: $1 did not refuse an unsigned write to $target" >&2; exit 1 ;;
        esac
    done
}

up() {
    dir="${1:?usage: archive-test-stack.sh up DIRECTORY}"
    mkdir -p "$dir/primary" "$dir/replica"
    down
    admin_key=ciadmin$(random); admin_secret=$(random)
    keeper_key=ciretention$(random); keeper_secret=$(random)
    replica_key=cireplica$(random); replica_secret=$(random)
    replica_keeper_key=cireplicaretention$(random); replica_keeper_secret=$(random)

    PYTHONPATH="$REPO" "$PYTHON" -m services.api_gateway.recording.storage.admin new-writer "$TENANT" > "$dir/writer.json"
    identities "$dir/primary/s3.json" "$admin_key:$admin_secret" "$keeper_key:$keeper_secret" "$dir/writer.json"
    identities "$dir/replica/s3.json" "$replica_key:$replica_secret" "$replica_keeper_key:$replica_keeper_secret"
    for site in primary replica; do
        printf '[jwt.signing]\nkey = "%s"\n[jwt.filer_signing]\nkey = "%s"\n' "$(random)" "$(random)" > "$dir/$site/security.toml"
    done
    chmod 0644 "$dir"/primary/* "$dir"/replica/*

    docker network create --subnet "$PRIMARY_SUBNET" "$NETWORK" >/dev/null
    docker network create "$LINK" >/dev/null
    docker run -d --name "$PRIMARY" --network "$NETWORK" --ip "$PRIMARY_ADDRESS" -p 127.0.0.1:58333:8333 \
        -v "$dir/primary:/etc/seaweedfs:ro" \
        "$IMAGE" server -dir=/data -s3 -s3.config=/etc/seaweedfs/s3.json \
        -ip="$PRIMARY_ADDRESS" -ip.bind=0.0.0.0 >/dev/null
    docker network connect "$LINK" "$PRIMARY"
    docker run -d --name "$REPLICA" --network "$LINK" -p 127.0.0.1:59333:8333 \
        -v "$dir/replica:/etc/seaweedfs:ro" \
        "$IMAGE" server -dir=/data -s3 -s3.config=/etc/seaweedfs/s3.json >/dev/null
    wait_s3 58333
    wait_s3 59333
    demand_jwt "$PRIMARY"
    demand_jwt "$REPLICA"
    docker run -d --name "$SYNC" --network "$LINK" \
        "$IMAGE" filer.sync -a="$PRIMARY:8888" -a.filerProxy -b="$REPLICA:8888" \
        -isActivePassive -b.doDeleteFiles=false \
        -a.path=/buckets -b.path=/buckets -a.excludePaths=/buckets/.system >/dev/null

    writer=$("$PYTHON" -c "import json,sys; w=json.load(open(sys.argv[1]))['gateway_writer'][sys.argv[2]]; print(w['access_key_id'] + ':' + w['secret_access_key'])" "$dir/writer.json" "$TENANT")
    cat > "$dir/archive-test.env" <<EOF
SSF_ARCHIVE_TEST_ENDPOINT=http://127.0.0.1:58333
SSF_ARCHIVE_TEST_REPLICA_ENDPOINT=http://127.0.0.1:59333
SSF_ARCHIVE_TEST_TENANT=$TENANT
SSF_ARCHIVE_TEST_ADMIN=$admin_key:$admin_secret
SSF_ARCHIVE_TEST_WRITER=$writer
SSF_ARCHIVE_TEST_RETENTION=$keeper_key:$keeper_secret
SSF_ARCHIVE_TEST_REPLICA_ADMIN=$replica_key:$replica_secret
SSF_ARCHIVE_TEST_REPLICA_RETENTION=$replica_keeper_key:$replica_keeper_secret
EOF
    echo "archive-test-stack.sh: up; source $dir/archive-test.env"
}

case "${1:-}" in
    up) up "${2:-}" ;;
    down) down ;;
    *) echo "usage: archive-test-stack.sh up DIRECTORY | down" >&2; exit 2 ;;
esac
