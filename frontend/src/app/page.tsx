"use client";

/** 训练台入口：令牌存在即进入工作台，否则先连接。 */

import { useEffect, useState } from "react";

import { TokenGate } from "@/components/TokenGate";
import { TrainingDesk } from "@/components/TrainingDesk";
import { loadToken } from "@/lib/token";

export default function Page() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setToken(loadToken());
    setReady(true);
  }, []);

  if (!ready) return null;

  return token ? (
    <TrainingDesk token={token} onUnauthorized={() => setToken(null)} />
  ) : (
    <TokenGate onConnected={setToken} />
  );
}
