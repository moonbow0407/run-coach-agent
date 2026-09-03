"use client";

/**
 * 开发态连接页：本仓库没有登录 API（user_id 只能由本地脚本签发进 JWT），
 * 首次使用时把 issue_token.py 生成的令牌粘贴进来。
 */

import { useEffect, useState } from "react";

import { checkBackendHealth } from "@/lib/api";
import { saveToken, tokenUserId } from "@/lib/token";
import { Eyebrow } from "@/components/ui";

export function TokenGate({ onConnected }: { onConnected: (token: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [backend, setBackend] = useState<"checking" | "up" | "down">("checking");

  useEffect(() => {
    void checkBackendHealth().then((health) => {
      setBackend(health.status === "ok" ? "up" : "down");
    });
  }, []);

  const connect = () => {
    const token = value.trim();
    if (!token) {
      setError("请粘贴令牌后再进入");
      return;
    }
    if (tokenUserId(token) === null) {
      setError("这不是有效的访问令牌，请重新签发");
      return;
    }
    saveToken(token);
    onConnected(token);
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Eyebrow>跑步教练 · 训练台</Eyebrow>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">连接你的教练</h1>
      <p className="mt-2 text-sm leading-relaxed text-mist">
        训练台通过本地签发的访问令牌识别身份。先在后端完成数据初始化，再粘贴令牌进入。
      </p>

      <ol className="mt-6 space-y-2 rounded-lg border border-hairline bg-paper p-4 text-sm leading-relaxed">
        <li>
          <code className="font-mono text-xs">python scripts/seed_demo.py</code>
          <span className="ml-1 text-mist">—— 写入演示数据</span>
        </li>
        <li>
          <code className="font-mono text-xs">
            python scripts/issue_token.py &lt;user_id&gt;
          </code>
          <span className="ml-1 text-mist">—— 签发令牌</span>
        </li>
      </ol>

      <label htmlFor="token" className="mt-6 font-mono text-[11px] uppercase tracking-[0.14em] text-mist">
        访问令牌
      </label>
      <input
        id="token"
        type="password"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") connect();
        }}
        placeholder="eyJhbGciOiJIUzI1NiIs…"
        className="mt-1.5 w-full rounded-lg border border-hairline bg-paper px-3 py-2.5 font-mono text-sm outline-none focus:border-asphalt"
      />
      {error ? <p className="mt-2 text-sm text-track-deep">{error}</p> : null}

      <button
        type="button"
        onClick={connect}
        className="mt-4 rounded-lg bg-asphalt px-4 py-2.5 text-sm font-medium text-paper transition-colors hover:bg-asphalt/85"
      >
        进入训练台
      </button>

      <p className="mt-6 font-mono text-[11px] uppercase tracking-[0.12em] text-mist">
        {backend === "checking"
          ? "检查后端连接…"
          : backend === "up"
            ? "● 后端已连接"
            : "○ 后端未连接——请先启动 uvicorn"}
      </p>
    </main>
  );
}
