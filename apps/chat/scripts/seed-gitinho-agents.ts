#!/usr/bin/env tsx
import { config } from "dotenv";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

config();
if (!process.env.POSTGRES_URL) {
  const rootEnv = resolve(process.cwd(), "../../.env");
  if (existsSync(rootEnv)) config({ path: rootEnv });
}

import { and, eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import { AgentTable, UserTable } from "lib/db/pg/schema.pg";
import { GITINHO_AGENTS, GitinhoAgentSpec } from "lib/ai/agent/gitinho-agents";
import { generateUUID } from "lib/utils";

const pool = new Pool({ connectionString: process.env.POSTGRES_URL! });
const db = drizzle(pool);

async function pickOwner(): Promise<{ id: string; email: string }> {
  const cliEmail = process.argv
    .slice(2)
    .find((a) => a.startsWith("--user="))
    ?.split("=")[1];
  if (cliEmail) {
    const [u] = await db
      .select({ id: UserTable.id, email: UserTable.email })
      .from(UserTable)
      .where(eq(UserTable.email, cliEmail));
    if (!u) throw new Error(`User with email ${cliEmail} not found`);
    return u;
  }
  const [admin] = await db
    .select({ id: UserTable.id, email: UserTable.email })
    .from(UserTable)
    .where(eq(UserTable.role, "admin"))
    .limit(1);
  if (admin) return admin;
  const [any] = await db
    .select({ id: UserTable.id, email: UserTable.email })
    .from(UserTable)
    .limit(1);
  if (!any)
    throw new Error(
      "No users in DB. Sign in once via GitHub OAuth, then re-run.",
    );
  return any;
}

async function upsert(spec: GitinhoAgentSpec, ownerId: string) {
  const [existing] = await db
    .select({ id: AgentTable.id })
    .from(AgentTable)
    .where(
      and(eq(AgentTable.name, spec.name), eq(AgentTable.userId, ownerId)),
    );

  if (existing) {
    await db
      .update(AgentTable)
      .set({
        description: spec.description,
        icon: spec.icon,
        instructions: spec.instructions,
        visibility: spec.visibility ?? "public",
        updatedAt: new Date(),
      })
      .where(eq(AgentTable.id, existing.id));
    return { id: existing.id, action: "updated" as const };
  }

  const id = generateUUID();
  await db.insert(AgentTable).values({
    id,
    name: spec.name,
    description: spec.description,
    icon: spec.icon,
    userId: ownerId,
    instructions: spec.instructions,
    visibility: spec.visibility ?? "public",
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  return { id, action: "created" as const };
}

async function main() {
  const owner = await pickOwner();
  console.log(`Owner: ${owner.email} (${owner.id})`);
  for (const spec of GITINHO_AGENTS) {
    const r = await upsert(spec, owner.id);
    console.log(`  ${r.action.padEnd(7)} @${spec.name} → ${r.id}`);
  }
}

main()
  .then(async () => {
    await pool.end();
    process.exit(0);
  })
  .catch(async (err) => {
    console.error(err);
    await pool.end();
    process.exit(1);
  });
