import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  assertGitHubOrgMembership,
  assertGitHubUserAllowed,
  getAllowedOrg,
  getAllowedUsers,
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

describe("getAllowedUsers", () => {
  const originalEnv = process.env.ALLOWED_USERS;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.ALLOWED_USERS;
    } else {
      process.env.ALLOWED_USERS = originalEnv;
    }
  });

  it("returns an empty list when env is unset or blank", () => {
    delete process.env.ALLOWED_USERS;
    expect(getAllowedUsers()).toEqual([]);
    process.env.ALLOWED_USERS = "   ";
    expect(getAllowedUsers()).toEqual([]);
  });

  it("parses a CSV, trims, and drops empty entries", () => {
    process.env.ALLOWED_USERS = " alice ,bob ,  ,carol,";
    expect(getAllowedUsers()).toEqual(["alice", "bob", "carol"]);
  });

  it("preserves a single login", () => {
    process.env.ALLOWED_USERS = "labanca";
    expect(getAllowedUsers()).toEqual(["labanca"]);
  });
});

describe("assertGitHubUserAllowed", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves when the user login is in the allowlist", async () => {
    mockFetchOnce({ body: { login: "alice" } });
    await expect(
      assertGitHubUserAllowed(TOKEN, ["alice", "bob"]),
    ).resolves.toBeUndefined();
  });

  it("matches case-insensitively", async () => {
    mockFetchOnce({ body: { login: "Alice" } });
    await expect(
      assertGitHubUserAllowed(TOKEN, ["ALICE"]),
    ).resolves.toBeUndefined();
  });

  it("throws a user-facing error when the login is not in the allowlist", async () => {
    mockFetchOnce({ body: { login: "carol" } });
    await expect(
      assertGitHubUserAllowed(TOKEN, ["alice", "bob"]),
    ).rejects.toThrow(/@carol ainda não está liberado/);
  });

  it("throws when GitHub returns a non-ok response", async () => {
    mockFetchOnce({ status: 502, body: { message: "Bad gateway" } });
    await expect(
      assertGitHubUserAllowed(TOKEN, ["alice"]),
    ).rejects.toThrow(/verificar seu usuário/);
  });

  it("sends the access token as a bearer credential", async () => {
    const spy = mockFetchOnce({ body: { login: "alice" } });
    await assertGitHubUserAllowed(TOKEN, ["alice"]);
    expect(spy).toHaveBeenCalledWith(
      "https://api.github.com/user",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
        }),
      }),
    );
  });
});
