> Generate a comprehensive session handoff file that captures everything needed to continue work seamlessly in a new Claude 
Code session.

CONTEXT CAPTURE REQUIREMENTS:

1. Session Metadata
   - Create filename: `handoff-{DD-MM-YYYY}-{HH-mm}.md` (e.g., handoff-28-10-2025-14-30.md)
   - Timestamp: Start/end time of current session
   - Current working directory and git branch
   - Active worktree (if using git worktrees)

2. Work Completed This Session
   - Files created/modified/deleted (with file paths)
   - Code changes summary (what was built/fixed)
   - Git commits made (commit messages and SHAs)
   - Tests run and results
   - Dependencies installed/updated

3. Current Project State
   - Active tasks from taskguard (if applicable)
   - Project structure overview (key directories/files)
   - Current architecture decisions
   - Integration points touched (APIs, databases, external services)

4. Context & Decisions Made
   - Technical decisions with rationale
   - Trade-offs chosen and why
   - Patterns established or followed
   - Known issues or limitations
   - Edge cases discovered

5. Next Steps & Continuity
   - Immediate next tasks (numbered, prioritized)
   - Blocked items requiring attention
   - Open questions or decisions needed
   - Files that need review
   - Testing/validation pending

6. Environment & Dependencies
   - Python/Node versions if relevant
   - Virtual environment details
   - MCP servers used
   - Tool configurations changed
   - Permission flags needed (--dangerously-skip-permissions)

7. Quick Reference
   - Key file paths for next session
   - Important code snippets or patterns used
   - Commands to resume work
   - Links to related documentation

FORMATTING REQUIREMENTS:
- Use clear markdown headers (##, ###)
- Include code blocks with syntax highlighting where relevant
- Use bullet points for lists, numbered lists for sequences
- Add horizontal rules (---) between major sections
- Keep each section concise but complete

VERIFICATION CHECKLIST:
- [ ] Can someone pick up work immediately from this file?
- [ ] Are all file paths absolute or clearly relative?
- [ ] Are decisions explained with enough context?
- [ ] Is git state clearly documented?
- [ ] Are next steps actionable and specific?

Save to: `./handoff-{DD-MM-YYYY}-{HH-mm}.md`

After generating, show me:
1. File path where saved
2. Quick summary of sections included
3. Top 3 next actions from handoff 