#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec tmp/bin/kubectl --kubeconfig tmp/kubeconfig "$@"
