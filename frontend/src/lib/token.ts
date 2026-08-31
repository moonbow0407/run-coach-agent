/** 认证令牌与会话线程的本地持久化。 */

const TOKEN_KEY = "run-coach.token";
const THREAD_KEY = "run-coach.thread-id";

export function loadToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function saveToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(THREAD_KEY);
}

export function loadThreadId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(THREAD_KEY);
}

export function saveThreadId(threadId: string): void {
  window.localStorage.setItem(THREAD_KEY, threadId);
}

/** 解析 JWT payload 的 sub（user_id），仅用于界面展示连接身份。 */
export function tokenUserId(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1] ?? "")) as {
      sub?: string;
    };
    return payload.sub ?? null;
  } catch {
    return null;
  }
}
