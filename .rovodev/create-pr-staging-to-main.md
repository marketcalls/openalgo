# Create PR from Staging to Main

Create a pull request from the staging branch to the main branch with an auto-generated title and body that showcases what changed in minimal text for easier understanding.

## Requirements

1. **Fetch latest changes** from both staging and main branches
2. **Analyze commits** on staging that are not yet on main
3. **Review file changes** and statistics (additions/deletions)
4. **Generate PR title** following conventional commit format (feat:, fix:, chore:, etc.)
5. **Create structured PR body** with:
   - Summary of changes
   - Key features/fixes added
   - Files changed statistics
   - Quality improvements
   - Impact assessment

## Output Format

- Use emoji icons for visual clarity (🚀, 🔍, 📊, ✅, 📦)
- Organize changes by category
- Keep descriptions concise and scannable
- Include commit count and file statistics
- Highlight major features and improvements

## Execution

Use GitHub CLI (`gh pr create`) to create the PR with:
- Base branch: `main`
- Head branch: `staging`
- Auto-generated title and body based on commit analysis

## Notes

- **Always use `--repo gopinathshiva/openalgo`** to ensure PR is created on your fork, not upstream
- The PR will target the `main` branch
