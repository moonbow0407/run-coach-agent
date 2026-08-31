/** HTTP 客户端：相对路径 + Bearer 令牌，经 Next.js rewrites 代理到 FastAPI。 */

import { clearToken, loadToken } from "@/lib/token";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export class UnauthorizedError extends ApiError {
  constructor() {
    super(401, "令牌无效或已过期");
  }
}

function extractDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = (detail as { code?: unknown }).code;
    if (code === "stale") return "提案状态已过期，请刷新后重试";
  }
  return "请求失败";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = loadToken();
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, { ...init, headers, cache: "no-store" });

  if (response.status === 401) {
    // 令牌失效是全局状态：清掉并回到连接页。
    clearToken();
    throw new UnauthorizedError();
  }
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body?.detail !== undefined) message = extractDetail(body.detail);
    } catch {
      // 响应不是 JSON 时保留状态码信息。
    }
    if (response.status === 404) throw new ApiError(404, message);
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string): Promise<T> {
  return request<T>(path, { method: "POST" });
}

export interface BackendHealth {
  status: string;
}

export async function checkBackendHealth(): Promise<BackendHealth> {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) return { status: "down" };
    return (await response.json()) as BackendHealth;
  } catch {
    return { status: "down" };
  }
}
