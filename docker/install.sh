apt update
apt install -y --no-install-recommends \
        autoconf \
        dvipng\
        automake \
        autotools-dev \
        build-essential \
        rsync\
        ca-certificates \
        curl \
        daemontools \
        ibverbs-providers \
        libibverbs1 \
        libkrb5-dev \
        librdmacm1 \
        libssl-dev \
        libtool \
        git \
        sudo \
        tmux \
        krb5-user \
        g++ \
        cmake \
        make \
        openssh-client \
        openssh-server \
        pkg-config \
        wget \
        nfs-common \
        libnuma1 \
        libnuma-dev \
        libpmi2-0-dev \
        unattended-upgrades \
        zsh \
        aria2 \
        vim \
        zip \
        unzip \
        pigz \
        ninja-build \
        htop \
        btop \
        git-lfs \
        libaio1 \
        libncurses-dev \
        sqlite3 \
        libsqlite3-dev\
        locales\
        poppler-utils\
        mesa-utils\
        tree\
        imagemagick\
        cm-super

wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
dpkg -i google-chrome-stable_current_amd64.deb

apt install -y --no-install-recommends libreoffice
