FROM mcr.microsoft.com/playwright:v1.63.0-jammy

WORKDIR /work
COPY package.json ./
RUN npm install

COPY playwright.config.js ./
COPY tests ./tests
CMD ["npm", "test"]
