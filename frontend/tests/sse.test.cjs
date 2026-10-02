const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

// 直接编译生产模块；仅替换认证依赖，fetch/ReadableStream 使用真实 Web API。
const source = fs.readFileSync(path.join(__dirname, "../src/lib/sse.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
class UnauthorizedError extends Error {}
let cleared = false;
const moduleBox = { exports: {} };
new Function("require", "module", "exports", compiled)((name) => {
  if (name === "@/lib/api") return { ApiError, UnauthorizedError };
  if (name === "@/lib/token") return { loadToken: () => "test", clearToken: () => { cleared = true; } };
  throw new Error(`Unexpected import: ${name}`);
}, moduleBox, moduleBox.exports);
const { streamChat } = moduleBox.exports;
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function mockResponse(t, chunks, { fail, cancelFails = false } = {}) {
  let index = 0;
  let cancelled = false;
  const body = new ReadableStream({
    pull(controller) {
      if (index < chunks.length) controller.enqueue(new TextEncoder().encode(chunks[index++]));
      else if (fail) controller.error(fail);
      else controller.close();
    },
    cancel() { cancelled = true; if (cancelFails) throw new Error("cleanup failed"); },
  });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  return { body, cancelled: () => cancelled };
}

test("分块、CRLF 和心跳正确解析，明确成功后释放 reader", async (t) => {
  const wire = ": heartbeat\n\n" + frame("run.started", { turn_id: "t", thread_id: "s" })
    + frame("response.delta", { content: "你好", step_index: 0 }) + frame("run.completed", {});
  const crlf = wire.replaceAll("\n", "\r\n");
  const { body } = mockResponse(t, [...crlf]);
  const events = [];
  await streamChat("hi", null, (event) => events.push(event));
  assert.deepEqual(events.map((event) => event.type), ["run.started", "response.delta", "run.completed"]);
  assert.equal(events[1].content, "你好");
  assert.equal(body.locked, false);
});

for (const [name, wire] of [
  ["损坏 JSON", "event: response.delta\ndata: {broken}\n\n"],
  ["缺少必要字段", frame("response.delta", { content: "hello" })],
  ["错误字段类型", frame("tool.completed", { call_id: "c", tool: "tool", status: "success", duration_ms: "1" })],
  ["空载荷", frame("run.started", null)],
]) {
  test(name + "必须报错，不能跳过后宣称成功", async (t) => {
    const { body } = mockResponse(t, [wire, frame("run.completed", {})]);
    const events = [];
    await assert.rejects(streamChat("hi", null, (e) => events.push(e)), /格式错误.*结果未知/);
    assert.equal(events.some((e) => e.type === "run.completed"), false);
    assert.equal(body.locked, false);
  });
}

test("没有终态的 EOF 和截断帧报告结果未知", async (t) => {
  const { body } = mockResponse(t, [frame("response.delta", { content: "half", step_index: 0 }), "event: run.completed\ndata: {"]);
  await assert.rejects(streamChat("hi", null, () => {}), /提前结束.*结果未知/);
  assert.equal(body.locked, false);
});

test("网络断开报告结果未知并释放 reader", async (t) => {
  const { body } = mockResponse(t, [], { fail: new TypeError("network") });
  await assert.rejects(streamChat("hi", null, () => {}), /连接中断.*结果未知/);
  assert.equal(body.locked, false);
});

test("用户取消保留 AbortError", async (t) => {
  const abort = new DOMException("aborted", "AbortError");
  const { body } = mockResponse(t, [], { fail: abort });
  await assert.rejects(streamChat("hi", null, () => {}), (error) => error === abort);
  assert.equal(body.locked, false);
});

for (const type of ["run.failed", "run.cancelled"]) {
  test(type + "作为明确终态交付", async (t) => {
    const { body } = mockResponse(t, [frame(type, { error: "执行失败" })]);
    const events = [];
    await streamChat("hi", null, (event) => events.push(event));
    assert.equal(events[0].type, type);
    assert.equal(body.locked, false);
  });
}

test("401 保留认证错误并清除令牌", async (t) => {
  cleared = false;
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  await assert.rejects(streamChat("hi", null, () => {}), UnauthorizedError);
  assert.equal(cleared, true);
});
