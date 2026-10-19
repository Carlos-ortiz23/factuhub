import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Turbopack otherwise walks up to the first lockfile it finds. There is an
  // unrelated package-lock.json outside this repository, which made Next warn
  // and infer the wrong root. Pin it to this workspace, deliberately narrow:
  // a broad root makes Turbopack watch far more files than it needs to.
  turbopack: {
    root: path.join(import.meta.dirname, "."),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
