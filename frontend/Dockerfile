# Vite needs the backend base path at build time. Compose sets this to /api;
# local Vite development continues to read frontend/.env.local directly.
FROM node:22-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY frontend/ ./
RUN npm run build

# The unprivileged Nginx image serves the static bundle as the final stage.
FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/

EXPOSE 3000
