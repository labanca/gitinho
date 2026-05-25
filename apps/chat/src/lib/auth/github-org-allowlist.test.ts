import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  assertGitHubOrgMembership,
  getAllowedOrg,
} from "./github-org-allowlist";

vi.mock("logger", () => ({
  default: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

const ORG = "splor-mg";
const TOKEN = "gho_test_token";

function mockFetchOnce(init: { status?: number; body?: unknown }) {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(init.body ?? []), {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  return fetchSpy;
}

describe("assertGitHubOrgMembership", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves when the org appears in /user/orgs", async () => {
    mockFetchOnce({ body: [{ login: "another-org" }, { login: "splor-mg" }] });
    await expect(
      assertGitHubOrgMembership(TOKEN, ORG),
    ).resolves.toBeUndefined();
  });

  it("matches case-insensitively", async () => {
    mockFetchOnce({ body: [{ login: "Splor-MG" }] });
    await expect(
      assertGitHubOrgMembership(TOKEN, ORG),
    ).resolves.toBeUndefined();
  });

  it("throws a user-facing error when the org is missing", async () => {
    mockFetchOnce({ body: [{ login: "other-org" }] });
    await expect(assertGitHubOrgMembership(TOKEN, ORG)).rejects.toThrow(
      /membro da organização 'splor-mg'/,
    );
  });

  it("throws when GitHub returns a non-ok response", async () => {
    mockFetchOnce({ status: 502, body: { message: "Bad gateway" } });
    await expect(assertGitHubOrgMembership(TOKEN, ORG)).rejects.toThrow(
      /verificar sua organização/,
    );
  });

  it("sends the access token as a bearer credential", async () => {
    const spy = mockFetchOnce({ body: [{ login: ORG }] });
    await assertGitHubOrgMembership(TOKEN, ORG);
    expect(spy).toHaveBeenCalledWith(
      "https://api.github.com/user/orgs",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
        }),
      }),
    );
  });
});

describe("getAllowedOrg", () => {
  const originalEnv = process.env.ALLOWED_ORG;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.ALLOWED_ORG;
    } else {
      process.env.ALLOWED_ORG = originalEnv;
    }
  });

  it("returns the env value when set", () => {
    process.env.ALLOWED_ORG = "splor-mg";
    expect(getAllowedOrg()).toBe("splor-mg");
  });

  it("throws if the env is missing or blank", () => {
    delete process.env.ALLOWED_ORG;
    expect(() => getAllowedOrg()).toThrow(/ALLOWED_ORG/);
    process.env.ALLOWED_ORG = "   ";
    expect(() => getAllowedOrg()).toThrow(/ALLOWED_ORG/);
  });
});
