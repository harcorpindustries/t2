import type { NextConfig } from "next";

// Static export: the FastAPI service on the server serves these files and the /api routes.
const config: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: false,
};

export default config;
