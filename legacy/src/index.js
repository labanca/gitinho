require('dotenv').config();
const express = require('express');
const { OpenAI } = require('openai');
const path = require('path');
const fs = require('fs').promises;

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, '../public')));

// Serve index.html for all routes
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '../public/index.html'));
});

// Initialize OpenAI client
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: process.env.OPENAI_API_BASE_URL,
  defaultQuery: { "api-version": "2023-05-15" },
  defaultHeaders: { "api-key": process.env.OPENAI_API_KEY }
});

// GitHub MCP integration
const githubMCP = {
  async getRepositoryInfo(owner, repo) {
    const response = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: {
        'Authorization': `Bearer ${process.env.GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github.v3+json'
      }
    });
    return await response.json();
  },

  async getRepositoryContent(owner, repo) {
    const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents`, {
      headers: {
        'Authorization': `Bearer ${process.env.GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github.v3+json'
      }
    });
    return await response.json();
  }
};

// Endpoint to analyze a repository
app.post('/analyze', async (req, res) => {
  try {
    const { owner, repo } = req.body;
    
    // Get repository information and contents
    const [repoInfo, repoContents] = await Promise.all([
      githubMCP.getRepositoryInfo(owner, repo),
      githubMCP.getRepositoryContent(owner, repo)
    ]);

    // Prepare context for AI analysis
    const context = {
      name: repoInfo.name,
      description: repoInfo.description,
      topics: repoInfo.topics,
      language: repoInfo.language,
      contents: repoContents.map(item => `${item.name} (${item.type})`).join('\n')
    };

    // Read the main prompt file
    const promptPath = path.join(__dirname, '../prompts/main_prompt.md');
    const systemPrompt = await fs.readFile(promptPath, 'utf8');

    // Generate AI analysis
    const analysis = await openai.chat.completions.create({
      model: "gpt-4o-mini-cursor",
      messages: [{
        role: "system",
        content: systemPrompt
      }, {
        role: "user",
        content: `Please analyze this repository and explain its purpose and structure:\n${JSON.stringify(context, null, 2)}`
      }]
    });

    res.json({
      repository: repoInfo.full_name,
      analysis: analysis.choices[0].message.content
    });
  } catch (error) {
    console.error('Error analyzing repository:', error);
    res.status(500).json({ error: 'Failed to analyze repository' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});