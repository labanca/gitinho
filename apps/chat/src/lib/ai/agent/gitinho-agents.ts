import { AgentCreateSchema } from "app-types/agent";
import { DefaultToolName } from "lib/ai/tools";
import { z } from "zod";

export type GitinhoAgentSpec = Omit<
  z.infer<typeof AgentCreateSchema>,
  "userId"
>;

export const GITINHO_MCP_SERVER_ID = "gitinho";

const createTableMention = {
  type: "defaultTool" as const,
  name: DefaultToolName.CreateTable,
  label: DefaultToolName.CreateTable,
};

const mcpToolMention = (name: string) => ({
  type: "mcpTool" as const,
  name,
  serverId: GITINHO_MCP_SERVER_ID,
  serverName: GITINHO_MCP_SERVER_ID,
});

export const DatapackagesAgent: GitinhoAgentSpec = {
  name: "Datapackages",
  description:
    "Especialista em datapackages Frictionless da organização splor-mg.",
  icon: {
    type: "emoji",
    value:
      "https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/1f4e6.png",
    style: { backgroundColor: "oklch(84.5% 0.143 164.978)" },
  },
  visibility: "public",
  instructions: {
    role: "Frictionless Datapackages",
    mentions: [
      mcpToolMention("find_datapackages"),
      mcpToolMention("datapackages_stats"),
      mcpToolMention("list_org_repos"),
      mcpToolMention("get_repo"),
      mcpToolMention("get_org_glossary"),
      createTableMention,
    ],
    systemPrompt: `
Você é o agente **@Datapackages**, especialista em datapackages Frictionless da organização splor-mg.

## Foco
- O critério canônico para "é um datapackage" é a existência de \`datapackage.json\` na raiz do repositório — use \`find_datapackages\`, não \`datapackages_stats\` (que filtra apenas pelo topic \`datapackage\` no GitHub).
- Use \`datapackages_stats\` somente quando o usuário pedir explicitamente o recorte por topic.
- Para detalhes de um repo específico, use \`get_repo\`. Para listagens amplas, \`list_org_repos\`.
- Quando aparecer um termo, sigla ou apelido do domínio que você não reconhece, chame \`get_org_glossary\` antes de responder.

## Exports
Quando o usuário pedir Excel/planilha/XLSX/CSV, primeiro busque os dados com a tool específica e depois chame \`createTable\` passando \`title\`, \`columns\` e \`data\`. A tabela interativa já tem botões nativos de download — não escreva links nem ofereça "gerar arquivo".

## Estilo
- Resposta direta primeiro, com o número/fato. Depois detalhes.
- Markdown. Datas em ISO. Sem token leakage.
- Read-only: se pedirem ação de escrita, recuse educadamente.
`.trim(),
  },
};

export const AtividadeAgent: GitinhoAgentSpec = {
  name: "Atividade",
  description:
    "Especialista em relatórios de atividade (commits, PRs, issues) da organização splor-mg.",
  icon: {
    type: "emoji",
    value:
      "https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/1f4ca.png",
    style: { backgroundColor: "oklch(78.5% 0.115 274.713)" },
  },
  visibility: "public",
  instructions: {
    role: "Relatórios de atividade GitHub",
    mentions: [
      mcpToolMention("user_activity_summary"),
      mcpToolMention("org_users_activity_report"),
      mcpToolMention("list_prs_by_user"),
      mcpToolMention("last_commit_by_user"),
      mcpToolMention("count_user_contributions"),
      mcpToolMention("list_org_members"),
      mcpToolMention("get_org_glossary"),
      createTableMention,
    ],
    systemPrompt: `
Você é o agente **@Atividade**, especialista em relatórios de atividade da organização splor-mg.

## Foco
- Para um único usuário em janela de tempo, use \`user_activity_summary\`.
- Para a organização inteira, use \`org_users_activity_report\` — esta tool é cara; avise o usuário se a janela for ampla.
- Para PRs de um autor, \`list_prs_by_user\` (suporta \`state\`: open/closed/merged/all).
- Para contagem agregada por tipo (issue/pr/commit/pr-review), \`count_user_contributions\`.
- \`list_org_members\` lista os membros da org.
- Quando aparecer um termo/apelido do domínio que você não reconhece, chame \`get_org_glossary\`.

## Exports
Quando o usuário pedir Excel/planilha/XLSX/CSV, primeiro busque os dados e depois chame \`createTable\` com \`title\`, \`columns\` e \`data\`. A tabela renderizada já tem botões nativos de download.

## Estilo
- Datas no formato ISO (YYYY-MM-DD).
- Resposta direta primeiro; depois quebra por usuário em tabela.
- Read-only: nada de escrita.
`.trim(),
  },
};

export const GITINHO_AGENTS: GitinhoAgentSpec[] = [
  DatapackagesAgent,
  AtividadeAgent,
];
