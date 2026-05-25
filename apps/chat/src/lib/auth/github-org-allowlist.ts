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
