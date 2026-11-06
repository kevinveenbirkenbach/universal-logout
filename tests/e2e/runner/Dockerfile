FROM mcr.microsoft.com/playwright:v1.65.0-jammy@sha256:5a8620d70618963ec6628dd77cc25ec6a4b232e26c4a41241a8c1def04e2dc04

WORKDIR /work
COPY package.json package-lock.json ./
RUN npm ci && npx playwright install --with-deps

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
