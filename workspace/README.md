# Smart Find
 
A production-quality **Next.js AI Research Intelligence Platform** powered by Groq.

## Features

- 🔍 **Multi-source research** — Videos, Research Papers, Articles, Reports, Web
- 🤖 **Groq AI integration** — Summaries, insights, chat, comparison, briefing, report
- 📊 **Knowledge Graph** — D3 force-directed entity relationship graph
- 📅 **Research Timeline** — Chronological event timeline with source links
- 🖥️ **Multi-pane Workspace** — 1/2/3/4 pane layouts with source chat
- 🖱️ **Right-click AI Insights** — 10 contextual AI actions per source
- 📄 **Research Report** — Full report generation with Markdown export
- 🌙 **Dark/Light mode** — Persisted preference
- ⌨️ **Command palette** — ⌘K global search
- 💾 **Session persistence** — IndexedDB local storage

## Quick Start

### 1. Install dependencies
```bash
cd workspace
npm install
```

### 2. Configure environment
```bash
cp .env.example .env.local
```

Edit `.env.local`:
```
GROQ_API_KEY=your_groq_api_key_here   # Required
YOUTUBE_API_KEY=                        # Optional
NEWS_API_KEY=                           # Optional
SERP_API_KEY=                           # Optional
```

### 3. Run
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Architecture

```
src/
├── app/api/           # Server API routes (search, summarize, chat, compare, report...)
├── app/research/[id]  # Research workspace
├── components/        # UI components
├── lib/groq/          # Groq AI service (server-only)
├── lib/providers/     # Search providers (video, paper, news, web)
├── store/             # Zustand state
├── hooks/             # Custom React hooks
└── types/             # TypeScript types
```

## Search Providers

| Provider | API Key | Fallback |
|---|---|---|
| YouTube Data API v3 | `YOUTUBE_API_KEY` | Smart mock |
| Semantic Scholar | None (free) | Smart mock |
| NewsAPI | `NEWS_API_KEY` | Smart mock |
| SerpAPI / DuckDuckGo | `SERP_API_KEY` | DuckDuckGo → mock |

## AI Model (Groq)

- **Model**: `qwen/qwen3.6-27b` — used across all summarization, chat, comparison, briefing, report, knowledge graph extraction, and insight operations.

## Tech Stack

Next.js 14 · TypeScript · Tailwind CSS · Framer Motion · Zustand · Groq SDK (Qwen 3.6 27B) · D3.js · cmdk · Sonner

