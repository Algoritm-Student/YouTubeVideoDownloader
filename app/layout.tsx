import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Bio Gaz — Landing",
  description: "Bio Gaz startup uchun zamonaviy landing page"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="uz">
      <body>{children}</body>
    </html>
  );
}
