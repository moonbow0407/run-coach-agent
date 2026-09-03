"use client";

/**
 * 训练台轻量 Markdown 解析渲染器：
 * 纯 React 节点生成，零第三方包依赖，天然杜绝 XSS。
 * 针对教练建议中的段落、分点清单、加粗、引用与等宽数据块做贴合训练台设计语言的排版。
 */

import React, { type ReactNode } from "react";

/** 行内标记解析：支持加粗 **text** 与行内代码 `code`。 */
function parseInline(text: string): ReactNode[] {
  const elements: ReactNode[] = [];
  // 正则匹配 **加粗** 或 `代码`
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      elements.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      elements.push(
        <strong key={`b-${match.index}`} className="font-semibold text-asphalt">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`") && token.endsWith("`")) {
      elements.push(
        <code
          key={`c-${match.index}`}
          className="rounded bg-fog px-1 py-0.5 font-mono text-[12px] text-asphalt"
        >
          {token.slice(1, -1)}
        </code>,
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    elements.push(text.slice(lastIndex));
  }

  return elements.length > 0 ? elements : [text];
}

export function Markdown({ content }: { content: string }) {
  if (!content) return null;

  const lines = content.split("\n");
  const nodes: ReactNode[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let listBuffer: { type: "ul" | "ol"; items: string[] } | null = null;

  const flushList = () => {
    if (!listBuffer) return;
    const { type, items } = listBuffer;
    const ListTag = type === "ul" ? "ul" : "ol";
    nodes.push(
      <ListTag
        key={`list-${nodes.length}`}
        className={`my-2 space-y-1 pl-5 text-sm leading-relaxed ${
          type === "ul" ? "list-disc" : "list-decimal"
        }`}
      >
        {items.map((item, idx) => (
          <li key={idx} className="text-asphalt">
            {parseInline(item)}
          </li>
        ))}
      </ListTag>,
    );
    listBuffer = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i] ?? "";

    // 代码块边界 ```
    if (rawLine.trim().startsWith("```")) {
      flushList();
      if (inCodeBlock) {
        // 代码块结束
        nodes.push(
          <pre
            key={`code-${nodes.length}`}
            className="my-2.5 overflow-x-auto rounded-lg border border-hairline bg-fog p-3 font-mono text-xs leading-relaxed text-asphalt"
          >
            <code>{codeBuffer.join("\n")}</code>
          </pre>,
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(rawLine);
      continue;
    }

    const trimmed = rawLine.trim();

    // 空行：重置列表并插入段落间隙
    if (!trimmed) {
      flushList();
      continue;
    }

    // 标题识别：###、##、#
    if (trimmed.startsWith("### ")) {
      flushList();
      nodes.push(
        <h4 key={`h4-${i}`} className="mt-3 mb-1 text-sm font-semibold tracking-tight text-asphalt">
          {parseInline(trimmed.slice(4))}
        </h4>,
      );
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flushList();
      nodes.push(
        <h3 key={`h3-${i}`} className="mt-3.5 mb-1.5 text-base font-semibold tracking-tight text-asphalt">
          {parseInline(trimmed.slice(3))}
        </h3>,
      );
      continue;
    }
    if (trimmed.startsWith("# ")) {
      flushList();
      nodes.push(
        <h2 key={`h2-${i}`} className="mt-4 mb-2 text-lg font-semibold tracking-tight text-asphalt">
          {parseInline(trimmed.slice(2))}
        </h2>,
      );
      continue;
    }

    // 块引用：> 
    if (trimmed.startsWith("> ")) {
      flushList();
      nodes.push(
        <blockquote
          key={`quote-${i}`}
          className="my-2 border-l-2 border-track/60 pl-3 text-sm italic text-mist"
        >
          {parseInline(trimmed.slice(2))}
        </blockquote>,
      );
      continue;
    }

    // 无序列表：- 或 *
    if (/^[-*]\s+/.test(trimmed)) {
      const itemContent = trimmed.replace(/^[-*]\s+/, "");
      if (listBuffer && listBuffer.type === "ul") {
        listBuffer.items.push(itemContent);
      } else {
        flushList();
        listBuffer = { type: "ul", items: [itemContent] };
      }
      continue;
    }

    // 有序列表：数字.
    if (/^\d+\.\s+/.test(trimmed)) {
      const itemContent = trimmed.replace(/^\d+\.\s+/, "");
      if (listBuffer && listBuffer.type === "ol") {
        listBuffer.items.push(itemContent);
      } else {
        flushList();
        listBuffer = { type: "ol", items: [itemContent] };
      }
      continue;
    }

    // 普通段落
    flushList();
    nodes.push(
      <p key={`p-${i}`} className="text-sm leading-relaxed text-asphalt">
        {parseInline(rawLine)}
      </p>,
    );
  }

  // 循环结束时清空未结束的块
  flushList();
  if (inCodeBlock && codeBuffer.length > 0) {
    nodes.push(
      <pre
        key={`code-${nodes.length}`}
        className="my-2.5 overflow-x-auto rounded-lg border border-hairline bg-fog p-3 font-mono text-xs leading-relaxed text-asphalt"
      >
        <code>{codeBuffer.join("\n")}</code>
      </pre>,
    );
  }

  return <div className="space-y-1.5">{nodes}</div>;
}
