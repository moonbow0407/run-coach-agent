import type { NextConfig } from "next";

// 后端 origin 通过环境变量注入，默认本机 8000 端口。
// 所有 /api/v1 请求经 Next.js rewrites 代理到 FastAPI，
// 前端代码只用相对路径，后端无需配置 CORS。
const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendOrigin}/api/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${backendOrigin}/health`,
      },
    ];
  },
};

export default nextConfig;
