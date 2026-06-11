import PyodideSmokeTest from "./pyodide-smoke-test";

// Smoke test pra Pyodide. Roda no browser depois do deploy, mostra
// pass/fail por etapa: (1) Pyodide carrega e executa Python, (2) o
// proxy /api/gh-proxy responde via pyfetch dentro do iframe, (3) o CSP
// do runner bloqueia tentativas de chamar api.github.com direto. Se
// alguma etapa falhar, o erro real fica visível na própria página —
// sem precisar conversar com o agente pra descobrir que quebrou.
//
// Gated pelo middleware (sessão obrigatória); não está em rota pública.

export const dynamic = "force-dynamic";

export default function Page() {
  const org = process.env.ALLOWED_ORG || "splor-mg";
  return <PyodideSmokeTest org={org} />;
}
