FROM debian:latest

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get -y install \
        curl \
        wget \
        perl-modules \
        build-essential \
        chrpath \
        libssl-dev \
        libxft-dev \
        libfreetype6 \
        libfreetype6-dev \
        libfontconfig1 \
        libfontconfig1-dev

RUN cd /tmp && \
    /usr/bin/wget https://bitbucket.org/ariya/phantomjs/downloads/phantomjs-2.1.1-linux-x86_64.tar.bz2

RUN cd /tmp && \
    /bin/tar xvjf phantomjs-2.1.1-linux-x86_64.tar.bz2 && \
    rm /tmp/phantomjs-2.1.1-linux-x86_64.tar.bz2 && \
    /bin/mv /tmp/phantomjs-2.1.1-linux-x86_64 /usr/local/share && \
    /bin/ln -sf /usr/local/share/phantomjs-2.1.1-linux-x86_64/bin/phantomjs /usr/local/bin

ENV PERLBREW_ROOT="/opt/perl5"

RUN curl -skL http://install.perlbrew.pl | bash && \
    echo ". $PERLBREW_ROOT/etc/bashrc" >> /etc/bash.bashrc && \
    bash -c '. $PERLBREW_ROOT/etc/bashrc && \
        perlbrew install-cpanm && \
        perlbrew install --notest --switch stable && \
        perlbrew switch `perlbrew list` && \
        perlbrew lib create local && \
        perlbrew switch @local'

WORKDIR /app
COPY cpanfile /app/
VOLUME /app

RUN bash -c '. $PERLBREW_ROOT/etc/bashrc && \
    cpanm -n -f --with-develop --with-all-features --installdeps /app'
