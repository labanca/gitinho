import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const BUILD_OUTPUT = process.env.NEXT_STANDALONE_OUTPUT
  ? "standalone"
  : undefined;

const isProd = process.env.NODE_ENV === "production";
const noHttps = process.env.NO_HTTPS === "1";

const csp = [
  "default-src 'self'",
  // Next.js precisa de inline + eval p/ dev; em prod restringimos.
  isProd
    ? "script-src 'self' 'unsafe-inline'"
    : "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://avatars.githubusercontent.com",
  "font-src 'self' data:",
  "connect-src 'self' https://api.github.com",
  // Next/Turbopack creates worker bundles via blob: URLs; without this
  // the JS code runner (`lib/code-runner/call-worker.ts`) trips CSP.
  "worker-src 'self' blob:",
  // The Pyodide runner (see /pyodide-runner) is the only place we allow
  // framing — same-origin only.
  "frame-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

// CSP escopada para /pyodide-runner. Esta rota hospeda o Pyodide num
// iframe isolado: precisa de blob: workers, WASM eval e do CDN da
// jsDelivr. Como o iframe é same-origin, o cookie de sessão acompanha,
// e o Python do usuário consegue chamar /api/gh-proxy (ainda gated por
// path allowlist + GET-only + auth do GitHub App). Mantemos os outros
// directives apertados — `frame-ancestors 'self'` impede que sites de
// terceiros embedem o runner, `connect-src` não inclui
// api.github.com de propósito (forçando todo tráfego de leitura a
// passar pelo proxy).
const runnerCsp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: https://cdn.jsdelivr.net",
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' https://cdn.jsdelivr.net",
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "form-action 'none'",
].join("; ");

const baseHardeningHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  ...(isProd && !noHttps
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains; preload",
        },
      ]
    : []),
];

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  ...baseHardeningHeaders,
];

// Sem X-Frame-Options: DENY aqui — o app principal precisa embedar este
// runner. `frame-ancestors 'self'` no CSP segura a restrição de origem.
const runnerHeaders = [
  { key: "Content-Security-Policy", value: runnerCsp },
  ...baseHardeningHeaders,
];

export default () => {
  const nextConfig: NextConfig = {
    output: BUILD_OUTPUT,
    cleanDistDir: true,
    devIndicators: {
      position: "bottom-right",
    },
    env: {
      NO_HTTPS: process.env.NO_HTTPS,
    },
    experimental: {
      taint: true,
      authInterrupts: true,
    },
    async headers() {
      return [
        {
          source: "/pyodide-runner",
          headers: runnerHeaders,
        },
        // Catch-all com negative lookahead — Next.js junta headers de
        // múltiplas regras que dão match, e com o mesmo key o
        // comportamento de merge não é previsível. Excluindo o runner
        // aqui garantimos que ele recebe APENAS o CSP relaxado.
        {
          source: "/((?!pyodide-runner).*)",
          headers: securityHeaders,
        },
      ];
    },
  };
  const withNextIntl = createNextIntlPlugin();
  return withNextIntl(nextConfig);
};
