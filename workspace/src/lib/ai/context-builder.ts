// src/lib/ai/context-builder.ts
// Builds structured, token-bounded context prompts for LLM queries

import { ContextItem } from '@/store/chat';

export interface FormatContextOptions {
  maxCharacters?: number;
  includeCitationsInstruction?: boolean;
}

/**
 * Formats active context items (documents, videos, images, web sources)
 * into a rich markdown block for LLM system/user prompts.
 */
export function formatContextForLLM(
  items: ContextItem[],
  options: FormatContextOptions = {}
): string {
  const { maxCharacters = 12000, includeCitationsInstruction = true } = options;

  if (!items || items.length === 0) {
    return '';
  }

  let output = '\n\n## 📚 RETRIEVED CONTEXT SOURCES\n';
  output += 'Use the following retrieved materials to inform your response. Always cite specific sources with [Source Name] or timestamp markers.\n\n';

  let currentLength = output.length;

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    let block = '';

    switch (item.type) {
      case 'document':
        block = `### [DOCUMENT ${i + 1}] ${item.title}\n`;
        if (item.metadata?.sectionTitle) {
          block += `Section: ${item.metadata.sectionTitle}\n`;
        }
        if (item.metadata?.pageNum) {
          block += `Page: ${item.metadata.pageNum}\n`;
        }
        block += `Content:\n${item.snippet || ''}\n\n`;
        break;

      case 'video':
        block = `### [VIDEO ${i + 1}] ${item.title}\n`;
        if (item.metadata?.timestamp || item.metadata?.startTime !== undefined) {
          block += `Timestamp: ${item.metadata.timestamp || item.metadata.startTime + 's'}\n`;
        }
        block += `Transcript Excerpt:\n${item.snippet || ''}\n\n`;
        break;

      case 'image':
        block = `### [IMAGE ${i + 1}] ${item.title}\n`;
        block += `Visual Description / OCR:\n${item.snippet || ''}\n\n`;
        break;

      case 'web':
        block = `### [WEB ${i + 1}] ${item.title}\n`;
        if (item.metadata?.url) {
          block += `URL: ${item.metadata.url}\n`;
        }
        block += `Snippet:\n${item.snippet || ''}\n\n`;
        break;

      default:
        block = `### [SOURCE ${i + 1}] ${item.title}\n${item.snippet || ''}\n\n`;
    }

    if (currentLength + block.length > maxCharacters) {
      const remainingChars = maxCharacters - currentLength - 50;
      if (remainingChars > 100) {
        output += block.slice(0, remainingChars) + '\n...[Context truncated]\n';
      }
      break;
    }

    output += block;
    currentLength += block.length;
  }

  if (includeCitationsInstruction) {
    output += '\n---\n**Instructions:**\n';
    output += '1. Base your answer primarily on the above context.\n';
    output += '2. If the context does not contain the answer, explicitly state what is missing.\n';
    output += '3. Reference sources accurately using brackets (e.g. `[Document 1]`, `[Video 1: 01:23]`, `[Web 1]`).\n';
  }

  return output;
}
