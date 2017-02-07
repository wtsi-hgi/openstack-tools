FROM ubuntu:16.04

ENV DEBIAN_FRONTEND noninteractive

# Install Go/Packer prerequisite, ansible, and openstack packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         apt-utils \
         software-properties-common \
    && apt-get install -y --no-install-recommends \
         gcc \
         git \
         python3-dev \
         python3-glanceclient \
         python3-keystoneauth1 \
         python3-setuptools \
    && rm -rf /var/lib/apt/lists/*

# Install glancecp
RUN cd /tmp \
    && git clone https://github.com/wtsi-hgi/openstack-tools.git \
    && cd openstack-tools \
    && python3 setup.py install

# Set workdir and entrypoint
WORKDIR /tmp
ENTRYPOINT []
