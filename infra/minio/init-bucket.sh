#!/bin/sh
# Runs once as the `minio-init` one-shot service in docker-compose.yml (image:
# minio/mc), after `minio` reports healthy. Creates the bucket the API and
# worker read/write source PDFs, rendered sheets/answer keys and scan images
# to (ALPPY_S3_BUCKET), and nothing else — no public policy, no extra users:
# the app talks to MinIO with the same access/secret key this script uses.
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set}"
: "${ALPPY_S3_BUCKET:=alppy}"
: "${ALPPY_S3_ENDPOINT_URL:=http://minio:9000}"

echo "minio-init: waiting for ${ALPPY_S3_ENDPOINT_URL} ..."
mc alias set local "${ALPPY_S3_ENDPOINT_URL}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

if mc ls "local/${ALPPY_S3_BUCKET}" >/dev/null 2>&1; then
  echo "minio-init: bucket '${ALPPY_S3_BUCKET}' already exists"
else
  mc mb "local/${ALPPY_S3_BUCKET}"
  echo "minio-init: created bucket '${ALPPY_S3_BUCKET}'"
fi

# Versioning off by default (MinIO's default); source PDFs and rendered
# sheets are addressed by content-derived keys (sha256 / job id), so
# overwrite-by-accident is not a real risk here and versioning would only
# add storage cost.
echo "minio-init: done"
