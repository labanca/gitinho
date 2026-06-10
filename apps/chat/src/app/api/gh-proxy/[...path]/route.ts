import "server-only";
import { getCurrentUser } from "lib/auth/permissions";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";

// Read-only GitHub proxy. The chat container holds the GitHub App private
// key; this endpoint mints an installation token on demand and forwards
// GETs to api.github.com under a strict path allowlist. Pyodide (browser)
// has no org credentials, so without this endpoint any Python script that
// needs to read org data 401s. With it, the agent can write arbitrary
// read-only analysis code.
//
// Defense layers:
//   1. Session required (org membership was already enforced at signin).
//   2. GET only — non-GET handlers below return 405.
//   3. Path allowlist: /repos/<ALLOWED_ORG>/..., /orgs/<ALLOWED_ORG>...
//   4. Path traversal blocked even when percent-encoded (decode then check).
//   5. Authorization headers from the caller are dropped; only the
//      installation token is forwarded upstream.

let cachedToken: { token: string; expiresAt: number } | null = null;

const PROXY_PREFIX = "/api/gh-proxy";

function base64urlEncode(input: Buffer | string): string {
  const buf = typeof input === "string" ? Buffer.from(input) : input;
  return buf
    .toString("base64")
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function mintAppJwt(): string {
  const appId = process.env.GH_APP_ID;
  const privateKeyPath = process.env.GH_APP_PRIVATE_KEY_PATH;
  if (!appId || !privateKeyPath) {
    throw new Error("GH_APP_ID/GH_APP_PRIVATE_KEY_PATH not configured");
  }
  const pem = readFileSync(privateKeyPath, "utf-8");
  const now = Math.floor(Date.now() / 1000);
  const header = base64urlEncode(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64urlEncode(
    JSON.stringify({ iat: now - 60, exp: now + 9 * 60, iss: appId }),
  );
  const data = `${header}.${payload}`;
  const sig = crypto.createSign("RSA-SHA256").update(data).sign(pem);
  return `${data}.${base64urlEncode(sig)}`;
}

async function getInstallationToken(): Promise<string> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 30_000) {
    return cachedToken.token;
  }
  const installationId = process.env.GH_APP_INSTALLATION_ID;
  if (!installationId) throw new Error("GH_APP_INSTALLATION_ID missing");
  const jwt = mintAppJwt();
  const resp = await fetch(
    `https://api.github.com/app/installations/${installationId}/access_tokens`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gitinho-chat-proxy/0.1",
      },
    },
  );
  if (!resp.ok) {
    cachedToken = null;
    throw new Error(`Token mint failed: HTTP ${resp.status}`);
  }
  const data = (await resp.json()) as { token: string; expires_at: string };
  cachedToken = {
    token: data.token,
    expiresAt: new Date(data.expires_at).getTime(),
  };
  return data.token;
}

function isAllowedPath(rawPath: string, org: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return false;
  }
  if (decoded.includes("..")) return false;
  const lc = decoded.toLowerCase();
  const orgLc = org.toLowerCase();
  return (
    lc.startsWith(`/repos/${orgLc}/`) ||
    lc === `/orgs/${orgLc}` ||
    lc.startsWith(`/orgs/${orgLc}/`)
  );
}

export async function GET(request: Request) {
  const user = await getCurrentUser();
  if (!user?.id) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const org = (process.env.ALLOWED_ORG || "splor-mg").toLowerCase();
  const url = new URL(request.url);
  if (!url.pathname.startsWith(`${PROXY_PREFIX}/`)) {
    return Response.json({ error: "Bad path" }, { status: 400 });
  }
  const ghPath = url.pathname.slice(PROXY_PREFIX.length);

  if (!isAllowedPath(ghPath, org)) {
    return Response.json(
      {
        error: `Path not allowlisted. Allowed prefixes: /repos/${org}/..., /orgs/${org}/...`,
      },
      { status: 403 },
    );
  }

  const upstream = new URL(`https://api.github.com${ghPath}`);
  url.searchParams.forEach((v, k) => upstream.searchParams.set(k, v));

  const accept = request.headers.get("accept") || "application/vnd.github+json";

  try {
    const token = await getInstallationToken();
    const resp = await fetch(upstream.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gitinho-chat-proxy/0.1",
      },
    });
    const body = await resp.text();
    return new Response(body, {
      status: resp.status,
      headers: {
        "Content-Type": resp.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (err) {
    return Response.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }
}

const methodNotAllowed = () =>
  new Response("Method Not Allowed", { status: 405 });

export const POST = methodNotAllowed;
export const PUT = methodNotAllowed;
export const DELETE = methodNotAllowed;
export const PATCH = methodNotAllowed;
