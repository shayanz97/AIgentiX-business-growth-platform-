"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Logo } from "@/components/app-shell";
import { LoginForm } from "@/components/forms/login-form";

function safeNext(value: string | null): string {
  // Only allow same-site relative paths (prevents open redirects such as //evil.example).
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

function LoginContent() {
  const router = useRouter();
  const params = useSearchParams();
  return (
    <LoginForm
      onSuccess={() => {
        router.replace(safeNext(params.get("next")));
        router.refresh();
      }}
    />
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(ellipse_at_top,_var(--color-navy-800),_var(--color-navy-950)_60%)] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>
        <div className="rounded-xl border border-line bg-navy-900/80 p-8 shadow-2xl shadow-black/40">
          <h1 className="text-xl font-semibold text-white">Sign in</h1>
          <p className="mb-6 mt-1 text-sm text-slate-400">Access your growth workspace.</p>
          <Suspense>
            <LoginContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
