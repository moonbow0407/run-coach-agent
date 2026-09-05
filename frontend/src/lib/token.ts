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

/** 只清会话线程、保留令牌：开启新话题时用。 */
export function clearThreadId(): void {
  window.localStorage.removeItem(THREAD_KEY);
}

export function loadThreadId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(THREAD_KEY);
}

export function saveThreadId(threadId: string): void {
  window.localStorage.setItem(THREAD_KEY, threadId);
}

/** 安全解码 Base64URL 字符串为 UTF-8 文本。 */
function decodeBase64Url(input: string): string {
  // 把 Base64URL 特殊字符还原为标准 Base64 字符
  const base64 = input.replace(/-/g, "+").replace(/_/g, "/");
  // 补齐末尾缺失的 '=' 填充符
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const binary = atob(padded);
  // 处理 UTF-8 多字节字符
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** 解析 JWT payload 的 sub（user_id），仅用于界面展示连接身份。 */
export function tokenUserId(token: string): string | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const json = decodeBase64Url(part);
    const payload = JSON.parse(json) as {
      sub?: string;
    };
    return payload.sub ?? null;
  } catch {
    return null;
  }
}
