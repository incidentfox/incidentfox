import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { SignInGate } from "@/components/SignInGate";
import { ThemeProvider } from "@/components/ThemeProvider";
import { VisitorSessionProvider } from "@/components/VisitorSessionProvider";
import { VisitorWarningBanner } from "@/components/VisitorWarningBanner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "IncidentFox",
  description: "AI-Powered SRE Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <head>
        {/* CRITICAL: This script MUST run before any rendering to prevent flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  const theme = localStorage.getItem('theme') || 'dark';
                  const root = document.documentElement;
                  if (theme === 'dark') {
                    root.classList.add('dark');
                    root.style.colorScheme = 'dark';
                  } else {
                    root.classList.remove('dark');
                    root.style.colorScheme = 'light';
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased h-full bg-gray-50 dark:bg-black`}
      >
        <ThemeProvider>
          <SignInGate>
            <VisitorSessionProvider>
              <div className="min-h-screen">
                <Sidebar />
                <main className="lg:pl-64 min-h-screen transition-all duration-200">{children}</main>
              </div>
              <VisitorWarningBanner />
            </VisitorSessionProvider>
          </SignInGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
