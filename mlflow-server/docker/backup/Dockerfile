FROM postgres:15-alpine

# Install backup utilities and diagnostic tools
RUN apk add --no-cache \
    # Backup tools
    gzip \
    tar \
    dcron \
    bash \
    # PostgreSQL client
    postgresql-client \
    # Network tools
    curl \
    wget \
    netcat-openbsd \
    bind-tools \
    # Process tools
    procps \
    htop \
    lsof \
    # Text editors
    vim \
    nano \
    # Utilities
    tree \
    jq

# Copy backup script
COPY backup.sh /backup.sh
RUN chmod +x /backup.sh

# Create backup directory
RUN mkdir -p /backups /var/log

ENTRYPOINT ["/backup.sh"]
