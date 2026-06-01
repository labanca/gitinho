import logger from "logger";

/**
 * Verify the GitHub user owning `accessToken` is a member of the allowlisted
 * organization, then throw if not.
 *
 * Uses `/user/orgs` (requires `read:org` scope). The endpoint only lists orgs
 * that the user has granted the OAuth app access to during the consent flow,
 * so a successful sign-in implies the user explicitly trusted Gitinho with
 * that org — matching the per-org grant model we want.
 */
export async function assertGitHubOrgMembership(
  accessToken: string,
  allowedOrg: string,
): Promise<void> {
  const target = allowedOrg.toLowerCase();
  const resp = await fetch("https://api.github.com/user/orgs", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });

  if (!resp.ok) {
    logger.error(
      `GitHub org allowlist check failed: HTTP ${resp.status} from /user/orgs`,
    );
    throw new Error(
      "Não foi possível verificar sua organização no GitHub. " +
        "Tente novamente em alguns minutos.",
    );
  }

  const orgs = (await resp.json()) as Array<{ login: string }>;
  const isMember = orgs.some((o) => o.login.toLowerCase() === target);

  if (!isMember) {
    logger.warn(
      `GitHub sign-in rejected: user is not a member of '${allowedOrg}'`,
    );
    throw new Error(
      `Acesso restrito: você precisa ser membro da organização '${allowedOrg}' ` +
        "no GitHub e autorizar o app Gitinho a acessar essa organização durante o login.",
    );
  }
}

export function getAllowedOrg(): string {
  const org = (process.env.ALLOWED_ORG ?? "").trim();
  if (!org) {
    throw new Error(
      "ALLOWED_ORG não está configurado. Defina o slug da organização (ex.: splor-mg) no .env.",
    );
  }
  return org;
}

/**
 * Reads `ALLOWED_USERS` as a CSV of GitHub logins (case-insensitive). Empty,
 * unset, or whitespace-only env yields an empty list — and `enforceGitHubOrgAllowlist`
 * skips the per-user check in that case, falling back to org-only access.
 */
export function getAllowedUsers(): string[] {
  const raw = (process.env.ALLOWED_USERS ?? "").trim();
  if (!raw) return [];
  return raw
    .split(",")
    .map((u) => u.trim())
    .filter((u) => u.length > 0);
}

/**
 * After org membership is confirmed, narrow access to a configured allowlist
 * of GitHub logins. Fetches `/user` (lightweight, ~1KB) to read the canonical
 * `login`. Caller MUST ensure `allowedUsers.length > 0`; an empty list would
 * lock everyone out and is not the intended "feature disabled" state.
 */
export async function assertGitHubUserAllowed(
  accessToken: string,
  allowedUsers: string[],
): Promise<void> {
  const resp = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });

  if (!resp.ok) {
    logger.error(
      `GitHub user allowlist check failed: HTTP ${resp.status} from /user`,
    );
    throw new Error(
      "Não foi possível verificar seu usuário no GitHub. " +
        "Tente novamente em alguns minutos.",
    );
  }

  const data = (await resp.json()) as { login: string };
  const userLogin = data.login.toLowerCase();
  const allowed = allowedUsers.map((u) => u.toLowerCase());

  if (!allowed.includes(userLogin)) {
    logger.warn(
      `GitHub sign-in rejected: user '${data.login}' is not in ALLOWED_USERS`,
    );
    throw new Error(
      `Acesso restrito: seu usuário @${data.login} ainda não está liberado no Gitinho. ` +
        "Solicite acesso ao time responsável.",
    );
  }
}
