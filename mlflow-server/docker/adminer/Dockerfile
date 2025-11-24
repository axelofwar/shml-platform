FROM adminer:latest

USER root

# Install diagnostic tools (Adminer uses Alpine Linux)
RUN apk add --no-cache \
    # Network tools
    curl \
    wget \
    netcat-openbsd \
    bind-tools \
    iputils \
    busybox-extras \
    # Database clients
    postgresql-client \
    # Process tools
    procps \
    htop \
    lsof \
    # Text editors
    vim \
    nano \
    # Utilities
    jq \
    tree

USER adminer
