## Contributing to Bunnify

Thank you for your interest in contributing to Bunnify! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a new branch for your feature or bugfix
4. Make your changes
5. Test your changes
6. Commit with clear, descriptive messages
7. Push to your fork
8. Submit a pull request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/bunnify.git
cd bunnify

# Install dependencies with uv
uv sync

# Run migrations
uv run python manage.py migrate

# Create test bookmarks
mkdir -p ~/work/bunnify
cp bunnify.json.example ~/work/bunnify/bunnify.json

# Load bookmarks
uv run python manage.py load_bookmarks

# Start development server
./bunnify-server --console --log-level DEBUG
```

> **Note:** Requires [uv](https://docs.astral.sh/uv/). Install with: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Code Style

- Follow PEP 8 guidelines for Python code
- Use type hints where appropriate
- Use pathlib for file operations
- Add docstrings to functions and classes
- Keep functions focused and modular

## Testing

Before submitting a PR:

1. Run the preflight script: `./scripts/checks`
2. If needed for faster iteration, run: `./scripts/checks --skip-integration`
3. Test your new feature/fix thoroughly
4. Verify command palette and Chrome integration behavior still works

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Update README.md if you add new features
- Add comments for complex logic
- Ensure code follows existing patterns
- Test with both IPv4 and IPv6 if network-related

## Areas for Contribution

- Additional bookmark management features
- UI/UX improvements
- Performance optimizations
- Documentation improvements
- Bug fixes
- New integrations (beyond GitHub)

## Questions?

Open an issue for questions or discussions about contributing.
