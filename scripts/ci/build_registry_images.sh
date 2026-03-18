#!/usr/bin/env bash
# SHML Platform - Container Registry Build Script
#
# Build order:
#   1. Base images (docker/base/) — shared foundation layers
#   2. Infrastructure images (postgres custom)
#   3. Inference service images (depend on base images)
#
# Environment:
#   CI_REGISTRY, CI_REGISTRY_IMAGE, CI_REGISTRY_USER, CI_REGISTRY_PASSWORD
#   SHML_IMAGE_TAG       (default: CI_COMMIT_SHA or "latest")
#   SHML_REGISTRY_IMAGE_PREFIX (default: $CI_REGISTRY_IMAGE/containers)
#   SHML_BUILD_TARGETS   (default: "all"; comma-separated to build subset)
#   SHML_LATEST_TAG      (default: "latest")
#   SHML_BUILD_ARGS      (optional extra --build-arg flags)

set -euo pipefail

: "${CI_REGISTRY:?CI_REGISTRY is required}"
: "${CI_REGISTRY_IMAGE:?CI_REGISTRY_IMAGE is required}"
: "${CI_REGISTRY_USER:?CI_REGISTRY_USER is required}"
: "${CI_REGISTRY_PASSWORD:?CI_REGISTRY_PASSWORD is required}"

IMAGE_TAG="${SHML_IMAGE_TAG:-${CI_COMMIT_SHA:-latest}}"
REGISTRY_PREFIX="${SHML_REGISTRY_IMAGE_PREFIX:-${CI_REGISTRY_IMAGE}/containers}"
BUILD_TARGETS="${SHML_BUILD_TARGETS:-all}"
LATEST_TAG="${SHML_LATEST_TAG:-latest}"

docker login "$CI_REGISTRY" -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD"

# Create/use buildx builder with registry cache support
if ! docker buildx inspect shml-builder >/dev/null 2>&1; then
    docker buildx create --name shml-builder --driver docker-container --use
else
    docker buildx use shml-builder
fi
docker buildx inspect --bootstrap >/dev/null

# =============================================================================
# STEP 1: Base images — must be built before any service that inherits them.
# These are always built when SHML_BUILD_TARGETS=all or contains "base-*".
# =============================================================================
# Format: "image-name|build-context|dockerfile"
BASE_IMAGES=(
    "base-python-cpu|docker/base|Dockerfile.python-cpu"
    "base-cuda-runtime|docker/base|Dockerfile.cuda-runtime"
    "base-python-gpu|docker/base|Dockerfile.python-gpu"
    "base-cuda-devel|docker/base|Dockerfile.cuda-devel"
    "base-cuda-cudnn|docker/base|Dockerfile.cuda-cudnn"
)

# =============================================================================
# STEP 2: Infrastructure images
# =============================================================================
INFRA_IMAGES=(
    "postgres-custom|postgres|Dockerfile"
)

# =============================================================================
# STEP 3: Inference service images (inherit from base images via --build-arg)
# =============================================================================
IMAGES=(
    "qwen3-vl-api|inference/qwen3-vl|Dockerfile"
    "z-image-api|inference/z-image|Dockerfile"
    "inference-gateway|inference/gateway|Dockerfile"
    "pii-blur-api|inference/pii-blur|Dockerfile"
    "pii-ui|inference/pii-ui|Dockerfile"
    "audio-copyright-api|inference/audio-copyright|Dockerfile"
    "gpu-manager|inference/gpu-manager|Dockerfile"
    "embedding-service|inference/embedding-service|Dockerfile"
    "coding-model-fallback|inference/coding-model|Dockerfile"
    "nemotron-coding|inference/nemotron|Dockerfile"
)

# =============================================================================
# Helper functions
# =============================================================================

should_build() {
    local image_name="$1"
    [[ "$BUILD_TARGETS" == "all" ]] && return 0

    IFS=',' read -ra requested <<< "$BUILD_TARGETS"
    for candidate in "${requested[@]}"; do
        [[ "$candidate" == "$image_name" ]] && return 0
    done
    return 1
}

build_image() {
    local image_name="$1"
    local build_context="$2"
    local dockerfile_path="$3"
    shift 3
    local extra_args=("$@")  # optional extra --build-arg flags

    local image_ref="${REGISTRY_PREFIX}/${image_name}"
    local cache_ref="${image_ref}:buildcache"

    local tags=(--tag "${image_ref}:${IMAGE_TAG}")
    if [[ "${CI_COMMIT_BRANCH:-}" == "${CI_DEFAULT_BRANCH:-}" ]]; then
        tags+=(--tag "${image_ref}:${LATEST_TAG}")
    fi

    echo "Building ${image_ref}:${IMAGE_TAG}"
    docker buildx build \
        --file "${build_context}/${dockerfile_path}" \
        --cache-from "type=registry,ref=${cache_ref}" \
        --cache-to "type=registry,ref=${cache_ref},mode=max" \
        --push \
        "${tags[@]}" \
        "${extra_args[@]}" \
        "$build_context"
}

# =============================================================================
# BUILD: Base images first
# =============================================================================
echo "=== Building base images ==="
for spec in "${BASE_IMAGES[@]}"; do
    IFS='|' read -r image_name build_context dockerfile_path <<< "$spec"
    if ! should_build "$image_name"; then
        echo "Skipping $image_name"
        continue
    fi

    # base-python-gpu needs to reference base-cuda-runtime from the registry
    if [[ "$image_name" == "base-python-gpu" ]]; then
        build_image "$image_name" "$build_context" "$dockerfile_path" \
            --build-arg "BASE_REGISTRY=${REGISTRY_PREFIX}" \
            --build-arg "BASE_TAG=${IMAGE_TAG}"
    else
        build_image "$image_name" "$build_context" "$dockerfile_path"
    fi
done

# =============================================================================
# BUILD: Infra images
# =============================================================================
echo "=== Building infrastructure images ==="
for spec in "${INFRA_IMAGES[@]}"; do
    IFS='|' read -r image_name build_context dockerfile_path <<< "$spec"
    if ! should_build "$image_name"; then
        echo "Skipping $image_name"
        continue
    fi
    build_image "$image_name" "$build_context" "$dockerfile_path"
done

# =============================================================================
# BUILD: Inference service images (pass BASE_REGISTRY so they can FROM $BASE_*)
# =============================================================================
echo "=== Building inference service images ==="
for spec in "${IMAGES[@]}"; do
    IFS='|' read -r image_name build_context dockerfile_path <<< "$spec"
    if ! should_build "$image_name"; then
        echo "Skipping $image_name"
        continue
    fi
    build_image "$image_name" "$build_context" "$dockerfile_path" \
        --build-arg "BASE_REGISTRY=${REGISTRY_PREFIX}" \
        --build-arg "BASE_TAG=${IMAGE_TAG}"
done

echo "=== Build complete ==="
