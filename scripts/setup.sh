#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test -f .env
mkdir -p tmp/bin logs results
if [ ! -x tmp/bin/kind ]; then
  curl -fL https://kind.sigs.k8s.io/dl/v0.27.0/kind-darwin-arm64 -o tmp/bin/kind
  chmod +x tmp/bin/kind
fi
if [ ! -x tmp/bin/kubectl ]; then
  curl -fL https://dl.k8s.io/release/v1.32.2/bin/darwin/arm64/kubectl -o tmp/bin/kubectl
  chmod +x tmp/bin/kubectl
fi
tmp/bin/kind create cluster --name lab5 --image kindest/node:v1.32.2 --config manifests/kind.yaml --kubeconfig tmp/kubeconfig
docker build --provenance=false -t lab5-pairs:1 .
tmp/bin/kind load docker-image lab5-pairs:1 --name lab5
scripts/kubectl.sh apply -f manifests/namespace.yaml
scripts/kubectl.sh -n lab5 create secret generic s3-credentials --from-env-file=.env
scripts/kubectl.sh apply -f manifests/priorities.yaml
