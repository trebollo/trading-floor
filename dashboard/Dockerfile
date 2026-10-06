FROM node:22-alpine AS dependencies
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS builder
COPY . .
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN corepack enable && addgroup -S dashboard && adduser -S dashboard -G dashboard
COPY --from=dependencies --chown=dashboard:dashboard /app/node_modules ./node_modules
COPY --from=builder --chown=dashboard:dashboard /app/.next ./.next
COPY --from=builder --chown=dashboard:dashboard /app/package.json ./package.json
COPY --from=builder --chown=dashboard:dashboard /app/next.config.ts ./next.config.ts
COPY --from=builder --chown=dashboard:dashboard /app/src ./src
USER dashboard
EXPOSE 3100
CMD ["pnpm", "start"]
