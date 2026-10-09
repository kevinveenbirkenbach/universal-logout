FROM mcr.microsoft.com/playwright:v1.64.0-jammy@sha256:c064e7f355d2dda32f669801a1b09e86a1e9252395c844d2cfbbe5c44acb9b79

WORKDIR /work
COPY package.json ./
RUN npm install && npx playwright install --with-deps

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
