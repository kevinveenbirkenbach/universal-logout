module.exports = [
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: {
        __dirname: "readonly",
        console: "readonly",
        document: "readonly",
        fetch: "readonly",
        getComputedStyle: "readonly",
        module: "writable",
        process: "readonly",
        require: "readonly",
        URL: "readonly",
        window: "readonly",
      },
    },
    rules: {
      eqeqeq: ["error", "always"],
      "no-undef": "error",
      "no-unused-vars": "error",
      "no-var": "error",
      "prefer-const": "error",
    },
  },
];
