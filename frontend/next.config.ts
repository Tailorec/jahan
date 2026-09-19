import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A second server (a test's) builds elsewhere, so it never contends with the one being developed in.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
