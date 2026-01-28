FROM mcr.microsoft.com/playwright:v1.47.2-jammy

WORKDIR /work
COPY package.json ./
RUN npm install

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
