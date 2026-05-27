import { createDbBasedMCPConfigsStorage } from "./db-mcp-config-storage";
import { createFileBasedMCPConfigsStorage } from "./fb-mcp-config-storage";
import {
  createMCPClientsManager,
  type MCPClientsManager,
} from "./create-mcp-clients-manager";
import { FILE_BASED_MCP_CONFIG } from "lib/const";
declare global {
  // eslint-disable-next-line no-var
  var __mcpClientsManager__: MCPClientsManager;
}

if (!globalThis.__mcpClientsManager__) {
  // Choose the appropriate storage implementation based on environment
  // NOTE: FILE_BASED_MCP_CONFIG is deprecated and will be removed in a future version.
  const storage = FILE_BASED_MCP_CONFIG
    ? createFileBasedMCPConfigsStorage()
    : createDbBasedMCPConfigsStorage();
  // autoDisconnectSeconds=0 → keep the MCP subprocess alive while the Node
  // process runs, so users never pay the ~10s spawn cost on a cold tool call.
  globalThis.__mcpClientsManager__ = createMCPClientsManager(storage, 0);
}

export const initMCPManager = async () => {
  return globalThis.__mcpClientsManager__.init();
};

export const mcpClientsManager = globalThis.__mcpClientsManager__;
