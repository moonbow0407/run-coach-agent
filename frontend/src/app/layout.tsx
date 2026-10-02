import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Archivo 可变字宽：标题用宽体、大数字用压缩体，号码布的字感。
// 中文回退到系统字体（PingFang / 微软雅黑），不为 CJK 引入数 MB 的 webfont。
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
});

const plex = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
});

export const metadata: Metadata = {
  title: "训练台 · 跑步教练",
  description: "面向业余跑者的长期自适应跑步教练：课表、状态与对话。",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${archivo.variable} ${plex.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
