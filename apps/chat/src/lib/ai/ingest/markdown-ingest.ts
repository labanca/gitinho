import { Buffer } from "node:buffer";
import { ChatAttachment } from "app-types/chat";
import { mcpClientsManager } from "lib/ai/mcp/mcp-manager";
import { storageKeyFromUrl } from "@/lib/file-storage/storage-utils";
import { GITINHO_MCP_SERVER_ID } from "@/lib/ai/agent/gitinho-agents";
import logger from "logger";

type MarkdownPreviewPart = {
  type: "text";
  text: string;
  ingestionPreview: true;
};

export type DownloadFile = (key: string) => Promise<Buffer>;

const SUPPORTED_EXTENSIONS = new Set([
  ".pdf",
  ".docx",
  ".doc",
  ".pptx",
  ".ppt",
  ".xlsx",
  ".xls",
  ".rtf",
  ".odt",
  ".epub",
]);

const SUPPORTED_MIME = new Set([
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/rtf",
  "application/vnd.oasis.opendocument.text",
  "application/epub+zip",
]);

const MAX_PREVIEW_CHARS = 20_000;

const extOf = (name: string) => {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
};

const isMarkdownable = (a: ChatAttachment, key: string) => {
  if (a.mediaType && SUPPORTED_MIME.has(a.mediaType)) return true;
  const ext = extOf(a.filename || key || "");
  return SUPPORTED_EXTENSIONS.has(ext);
};

const extractMarkdown = (toolResult: unknown): string | null => {
  const result = toolResult as
    | { content?: Array<{ type?: string; text?: string }> }
    | undefined;
  const text = result?.content?.find((c) => c?.type === "text")?.text;
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    if (parsed?.ok && typeof parsed.markdown === "string") {
      return parsed.markdown as string;
    }
    if (parsed?.ok === false) {
      logger.warn(
        `convert_document failed: ${parsed.error ?? "unknown error"}`,
      );
    }
  } catch {
    return text;
  }
  return null;
};

const formatPreview = (filename: string, markdown: string): string => {
  const trimmed =
    markdown.length > MAX_PREVIEW_CHARS
      ? `${markdown.slice(0, MAX_PREVIEW_CHARS)}\n\n[... preview truncated at ${MAX_PREVIEW_CHARS} chars of ${markdown.length}]`
      : markdown;
  return `Preview of ${filename} (converted to markdown):\n\n${trimmed}`;
};

export const buildMarkdownIngestionPreviewParts = async (
  attachments: ChatAttachment[],
  download: DownloadFile,
): Promise<MarkdownPreviewPart[]> => {
  if (!attachments?.length) return [];

  const results = await Promise.all(
    attachments.map(async (attachment) => {
      if (attachment.type !== "source-url") return null;
      const key = storageKeyFromUrl(attachment.url);
      if (!key) return null;
      if (!isMarkdownable(attachment, key)) return null;

      try {
        const buffer = await download(key);
        const toolResult = await mcpClientsManager.toolCallByServerName(
          GITINHO_MCP_SERVER_ID,
          "convert_document",
          {
            content_base64: buffer.toString("base64"),
            filename: attachment.filename || key,
          },
        );
        const markdown = extractMarkdown(toolResult);
        if (!markdown) return null;
        return {
          type: "text",
          text: formatPreview(attachment.filename || key, markdown),
          ingestionPreview: true as const,
        };
      } catch (error) {
        logger.warn(
          `markdown ingest failed for ${attachment.filename ?? key}: ${error}`,
        );
        return null;
      }
    }),
  );

  return results.filter(Boolean) as MarkdownPreviewPart[];
};
