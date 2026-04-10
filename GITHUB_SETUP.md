# GitHub Setup Guide

## Creating the Repository on GitHub

1. Go to https://github.com/new
2. Fill in the details:
   - **Repository name:** `bunnify`
   - **Description:** "A powerful Django-based bookmark manager with command palette, Chrome integration, and GitHub Copilot code reviews"
   - **Visibility:** Public (or Private if preferred)
   - **DO NOT** initialize with README, .gitignore, or license (we already have these)
3. Click "Create repository"

## Pushing to GitHub

After creating the repository on GitHub, run these commands:

```bash
cd /Users/hcma/work/ai/bunnify

# Add GitHub as remote
git remote add origin https://github.com/thehcma/bunnify.git

# Push main branch
git push -u origin main
```

## Setting Up Repository Settings

### Topics (for discoverability)
Go to repository → About section → Settings (⚙️) → Add topics:
- `django`
- `bookmark-manager`
- `url-shortener`
- `chrome-extension`
- `github-copilot`
- `python3`
- `command-palette`

### Branch Protection (Optional)
Settings → Branches → Add branch protection rule for `main`:
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- Select: `test (3.14)`

### Repository Description
Update the description to:
```
🐰 A powerful Django bookmark manager with command palette, Chrome integration, and GitHub Copilot code reviews
```

## Verifying GitHub Actions

After pushing, go to:
https://github.com/thehcma/bunnify/actions

You should see the Django CI workflow running. It will:
- Test on Python 3.14
- Run Django checks
- Run migrations
- Validate example bookmark file

## Clone URL for Others

Once pushed, others can clone with:
```bash
git clone https://github.com/thehcma/bunnify.git
```

## Done!

Your repository is now ready at:
https://github.com/thehcma/bunnify

Remember to update the `pr` bookmark URL in your personal `~/work/bunnify/bunnify.json` 
to point to your actual repositories.
