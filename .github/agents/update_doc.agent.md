---
# Fill in the fields below to create a basic custom agent for your repository.
# The Copilot CLI can be used for local testing: https://gh.io/customagents/cli
# To make this agent available, merge this file into the default repository branch.
# For format details, see: https://gh.io/customagents/config

name: update-doc
description: A standard workflow to update the documentation. It applies to all agent tasks.
---

When to do: Update the documentation when you finish the task.
Where to do: The documentation is located at docs.
What and How to do: Modify and update the corresponding documentation based on the code.
  - Summarize the changes
  - Check for discrepancies between the existing documentation and the modified content, such as method names, method functions, class names, class functions, file paths, etc.
  - Update the documentation content
