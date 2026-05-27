FROM ghcr.io/prefix-dev/pixi:latest

# We need tailscale and podman client inside the container
# The pixi base image is likely Debian/Ubuntu based
USER root
RUN apt-get update && apt-get install -y \
    podman \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://pkgs.tailscale.com/stable/debian/bullseye.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null \
    && curl -fsSL https://pkgs.tailscale.com/stable/debian/bullseye.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list \
    && apt-get update && apt-get install -y tailscale && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Install dependencies using pixi
RUN pixi install

EXPOSE 5000

ENV FLASK_APP=app.py
ENV FLASK_SECRET_KEY=nasypeasy-prod-secret-change-me

# Expose python and pixi binaries properly if needed, but pixi run handles it
CMD ["pixi", "run", "start"]
