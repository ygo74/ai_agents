# Get started with an agent

Use one virtual environment per agent. The Mail Agent and Wiki Agent use
different frameworks and dependency sets.

## Requirements

- Windows PowerShell for the commands below (the repository also works from a
  Python 3.12 shell on other supported platforms)
- Python 3.12 or newer
- An OpenAI or Azure OpenAI model configuration

## Install and configure the Wiki Agent

Run these commands from the repository root:

```powershell
py -3.12 -m scripts.install --env wiki-agent --into .venvs\wiki-agent
Copy-Item .env.example .env
```

Edit `.env` and set `AGENT_CHAT_PROVIDER`, the model name, and the provider
credential. For OpenAI, use `AGENT_CHAT_PROVIDER=openai`,
`OPENAI_API_KEY=<your key>`, and `OPENAI_CHAT_MODEL=gpt-4o-mini`.

Start the Wiki Agent against the delivered local dataset:

```powershell
$env:WIKI_AGENT_MODE = "mock"
.\.venvs\wiki-agent\Scripts\wiki-agent.exe
```

Ask `What is in scope for the Apollo project?`. The agent searches the local
dataset and answers with wiki citations. The model provider still needs network
access and a valid credential. For the Mail Agent, replace `wiki-agent` with
`mail-agent` and use its [Mail guide](mail-agent.md).

For the other run modes and their requirements, continue with
[Running the Wiki Agent](wiki-agent-running.md). The full environment
installer and development setup are in the root [README](../../README.md).
