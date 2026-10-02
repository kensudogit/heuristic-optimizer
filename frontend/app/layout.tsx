import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "工場建設レイアウト最適化 PoC",
  description: "貪欲法と局所探索による工場レイアウトのヒューリスティック探索",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
