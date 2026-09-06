FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
# Backend-URL, mit der das Frontend im Browser spricht (siehe scripts/build.mjs).
ARG API_BASE_URL=http://localhost:8000
ENV API_BASE_URL=$API_BASE_URL
RUN npm run build

FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json ./
# Nur Laufzeit-Abhängigkeiten (pdfjs-dist) – der eigene dev-server.mjs
# liefert es per Importmap direkt aus node_modules aus, ganz ohne Bundling.
RUN npm install --omit=dev
COPY --from=build /app/dist ./dist
COPY scripts/dev-server.mjs ./scripts/dev-server.mjs
# Zur Laufzeit erneut gesetzt (ARGs aus dem Build-Stage gelten nicht mehr) -
# dev-server.mjs braucht die Backend-Herkunft für die img-src/connect-src
# Content-Security-Policy.
ARG API_BASE_URL=http://localhost:8000
ENV API_BASE_URL=$API_BASE_URL
EXPOSE 5173
CMD ["node", "scripts/dev-server.mjs"]
