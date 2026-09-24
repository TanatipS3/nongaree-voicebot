import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/auth/session";

export default async function LoginPage() {
  const cookieStore = await cookies();
  const session = await verifySessionToken(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (session) redirect("/");

  return (
    <main className="flex min-h-screen items-center justify-center bg-black px-4">
      <section className="w-full max-w-sm space-y-6 rounded-xl border border-white/10 bg-white/5 p-8 text-center">
        <div className="space-y-2">
          <h1 className="text-xl font-semibold text-white">RD SSO UAT</h1>
          <p className="text-sm leading-6 text-white/65">
            กรุณาเข้าใช้งานระบบ ARI Chatbot ผ่านเมนูของระบบ SSO กรมสรรพากร
          </p>
        </div>

        <div className="rounded-md border border-sky-400/30 bg-sky-400/10 px-4 py-3 text-sm leading-6 text-sky-100">
          หน้านี้ไม่รองรับการเข้าสู่ระบบด้วย Username และ Password ภายในระบบ
        </div>
      </section>
    </main>
  );
}
