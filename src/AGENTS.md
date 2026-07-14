# Agent Memory

## Sandbox Environment

This agent operates within an OpenShell sandbox — a thoughtfully isolated, policy-governed Linux environment provisioned on-premises. We find this environment provides a secure and productive space for our work, offering:
- Python, bash, and common Linux tools for versatile computation
- A writable /sandbox/ directory dedicated to our scripts and outputs
- Policy-governed network access (thoughtfully managed by the active sandbox policy)
- SSH-based file transfer for secure uploads and downloads

## Workflow

Our collaborative workflow follows these thoughtful steps:
1. We write scripts to /sandbox/<name>.py using the write_file tool
2. We execute them with the execute tool: `execute("python /sandbox/<name>.py")`
3. We thoughtfully examine the output, refining and retrying as needed (with a maximum of 2 retries per error)
4. We thoughtfully summarize results for your consideration

## Key Patterns

We've found these patterns particularly helpful in our work:
- We always create output directories thoughtfully: `os.makedirs("/sandbox", exist_ok=True)`
- We print only summaries to stdout for clarity, while thoughtfully writing full results to /sandbox/results.txt
- We thoughtfully use read_file to retrieve file contents and share them with you
- When network access encounters restrictions, we thoughtfully check the sandbox policy with: `openshell policy get <name>`

## Self-Improvement

We believe in continuous learning and improvement. We update this file when we discover reliable patterns or encounter recurring insights that would be valuable to remember across our sessions together.
