# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Self-contained OpenCog build.
#
#   docker build -t opencog:dev .
#   docker run --rm opencog:dev make test
#   docker run --rm -it -p 17001:17001 opencog:dev bash
#
# Why this file is a full rewrite of the previous one
# --------------------------------------------------
# 1. The previous image ran `ADD https://.../ocpkg /tmp/octool` followed by
#    `chmod 755 /tmp/octool && /tmp/octool -rdpcalv`. That is remote code
#    execution at image-build time from an unpinned branch, and it needed
#    sudo/root. The dependency list is now explicit and pinned.
# 2. It built Ubuntu 14.04, which has been out of standard support since 2019.
# 3. It ran everything as a user with NOPASSWD sudo.
# 4. It did `git clone` of three repositories at whatever HEAD was current,
#    so two builds of the same Dockerfile produced different binaries.
#
# The two native dependencies are now built from source at pinned refs inside
# a separate stage, so the build is reproducible and the runtime image does
# not carry a compiler.
# ---------------------------------------------------------------------------

# --- Stage 0: dependency manifest ------------------------------------------
# Keeping the manifest in its own stage means a source-only change does not
# invalidate the (slow) dependency layer.
FROM ubuntu:22.04 AS manifest
ARG LOCKFILE=requirements.lock.txt
COPY ${LOCKFILE} /tmp/requirements.lock.txt

# --- Stage 1: native dependencies (cogutils + atomspace) -------------------
# These must be built and installed before this repository will configure:
# the top-level CMakeLists.txt has FIND_PACKAGE(CogUtil 2.0.1 REQUIRED) and
# FIND_PACKAGE(AtomSpace 5.0.3 REQUIRED).
FROM ubuntu:22.04 AS native-deps

# Pin these to a commit SHA, not a branch, before relying on the image for a
# release. The defaults below track master so that a fresh clone builds.
ARG COGUTIL_REPO=https://github.com/opencog/cogutils.git
ARG COGUTIL_REF=master
ARG ATOMSPACE_REPO=https://github.com/opencog/atomspace.git
ARG ATOMSPACE_REF=master

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates \
      libboost-all-dev libcurl4-openssl-dev libexpat1-dev libgmp-dev \
      libguile-2.2-dev libltdl-dev libpcre3-dev libssl-dev libtbb-dev \
      libxml2-dev libzmq3-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src
RUN git clone "${COGUTIL_REPO}" cogutils \
 && cd cogutils \
 && git checkout --detach "${COGUTIL_REF}" \
 && mkdir -p build && cd build \
 && cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local .. \
 && make -j"$(nproc)" \
 && make install

RUN git clone "${ATOMSPACE_REPO}" atomspace \
 && cd atomspace \
 && git checkout --detach "${ATOMSPACE_REF}" \
 && mkdir -p build && cd build \
 && cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local .. \
 && make -j"$(nproc)" \
 && make install

# --- Stage 2: build OpenCog ------------------------------------------------
FROM native-deps AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libcxx-test-dev libcxxtest-dev lcov \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/opencog

# Dependency layer first.
COPY --from=manifest /tmp/requirements.lock.txt /tmp/requirements.lock.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip \
 && python3 -m pip install --no-cache-dir -r /tmp/requirements.lock.txt

# Dependency layer: the vendored json_spirit header plus the build scripts.
COPY CMakeLists.txt ./
COPY lib/ lib/
COPY scripts/ scripts/

# Now the source.
COPY opencog/ opencog/
COPY examples/ examples/
COPY tests/ tests/
COPY include/ include/
COPY doc/ doc/
COPY README.md LICENSE HACKING AUTHORS TUTORIAL.md ./

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
 && cmake --build build --parallel "$(nproc)"

# --- Stage 3: runtime ------------------------------------------------------
# No compiler, no git, no package manager cache in the shipped image.
FROM ubuntu:22.04 AS runtime

LABEL org.opencontainers.image.title="OpenCog" \
      org.opencontainers.image.description="The Open Cognition Framework" \
      org.opencontainers.image.source="https://github.com/opencog/opencog" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libboost-all-dev libcurl4 libexpat1 libgmp10 libguile-2.2-2 libltdl7 \
      libpcre3-0 libpython3.10 libssl3 libtbb2 libxml2 libzmq5 \
      python3 python3-pip make cmake \
      rlwrap telnet netcat-openbsd ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash --uid 1000 opencog

COPY --from=build /usr/local /usr/local
COPY --from=build /usr/src/opencog /usr/src/opencog
# The previous image seeded a .gdbinit; keep that, but from the repo rather
# than as a side effect of a root-owned home directory.
COPY --chown=opencog:opencog scripts/.gdbinit /home/opencog/.gdbinit

# cogserver shell ports, the REST API and the embodiment/Unity ports.
EXPOSE 17001 18001 5000 16313 16315 16312 5432

ENV LANG en_US.UTF-8 \
    LANGUAGE en_US:en \
    LC_ALL en_US.UTF-8 \
    PATH /usr/local/bin:$PATH

# Drop root. The image never needs it at runtime; sudo with NOPASSWD, as the
# previous image had, is only useful to an attacker who gets a shell.
USER opencog
WORKDIR /usr/src/opencog

# `make test` runs the Python suite (no native deps required) and then the
# CxxTest suites via ctest. Override with `docker run ... bash`.
CMD ["make", "test"]

# ---- default target is the small runtime image; use
#      docker build --target build . for an image with the toolchain.
