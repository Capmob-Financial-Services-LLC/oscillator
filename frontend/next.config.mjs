/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The AWS build (deploy/aws/buildspec.yml) sets NEXT_OUTPUT=standalone to get
  // a self-contained server for Lambda. Unset everywhere else (Vercel, dev).
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}),
};

export default nextConfig;
