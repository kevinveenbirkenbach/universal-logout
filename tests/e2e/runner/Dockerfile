FROM mcr.microsoft.com/playwright:v1.64.1-jammy@sha256:6075bd984554db82aee96bcdde53197f091dfe8c4b89322c61da77b86308b810

WORKDIR /work
COPY package.json package-lock.json ./
RUN npm ci && npx playwright install --with-deps

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
