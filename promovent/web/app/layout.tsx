import type { Metadata, Viewport } from "next";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = { title: "Promovent", description: "Crypto market intelligence, research and risk-controlled trading." };
export const viewport: Viewport = { colorScheme: "dark", themeColor: "#0e1116", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
