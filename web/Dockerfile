FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

ARG NEXT_PUBLIC_DATAPILOT_API=http://127.0.0.1:8000/api/v1
ENV NEXT_PUBLIC_DATAPILOT_API=${NEXT_PUBLIC_DATAPILOT_API}

RUN npm run lint && npm test

FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    PORT=3000

WORKDIR /app

COPY --from=build --chown=node:node /app ./

USER node
EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
