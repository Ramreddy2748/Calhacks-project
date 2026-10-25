FROM node:22.14-bookworm-slim AS node
FROM clockworklabs/spacetime@sha256:dc66a9d8d48b210f6b9c1f2c5d6aa47adbada5e37350f898782a59c2d9f9d1b8 AS builder
USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /module
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY src ./src
COPY tsconfig.json ./
RUN /opt/spacetime/spacetimedb-cli build --module-path /module

FROM scratch AS artifact
COPY --from=builder /module/dist/bundle.js /bundle.js
