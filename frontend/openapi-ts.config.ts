import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../docs/openapi.yaml",
  output: "src/api/generated",
  client: "@hey-api/client-fetch",
});
