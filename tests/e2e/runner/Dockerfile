FROM mcr.microsoft.com/playwright:v1.64.1-jammy@sha256:7e9f074b4b69f7c746865936ac7840733cf5dfc957f265a547f331e7b83922d7

WORKDIR /work
COPY package.json package-lock.json ./
RUN npm ci && npx playwright install --with-deps

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
