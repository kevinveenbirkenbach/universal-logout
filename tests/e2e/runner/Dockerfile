FROM mcr.microsoft.com/playwright:v1.47.2-jammy@sha256:eee5be766a342139241c9a51e6449cb8f6ff2847fbd0792f91793aaf0c7f4f46

WORKDIR /work
COPY package.json ./
RUN npm install && npx playwright install --with-deps

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
