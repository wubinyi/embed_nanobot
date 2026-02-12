# How to Enable the SKILL in GitHub Copilot
The copilot-instructions.md file is automatically loaded by GitHub Copilot in VS Code — no extra configuration needed. It acts as a persistent system prompt for every Copilot Chat session in this repository.

Example prompts to activate the workflow:

| What you want | Prompt | 
|---|------|
| Start a new session | `bootstrap` or `"Let's start a new session"` |
| Quick resume | `"quick bootstrap"` or `"let's continue"` |
| Start a feature | `"Let's implement PSK authentication for the mesh layer"` |
| Trigger upstream sync | `"Sync with upstream"` or `"Run the upstream sync protocol"` |
| Check doc freshness | `"Run the documentation freshness check"` |
| Review roadmap | `"Review the project roadmap"` or `"What's next on the roadmap?"` |
| After a refactor | `"Upstream has refactored — run the refactoring response protocol"` |
| Design review only | `"Design phase only — plan the device registry feature"` |

The multi-agent flow (Architect → Reviewer → Developer → Tester) activates automatically when you ask Copilot to implement a feature. The bootstrap protocol runs when you start a new conversation.