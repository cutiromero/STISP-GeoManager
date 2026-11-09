# Version management Makefile for huyang_system
.DEFAULT_GOAL := help

.PHONY: help version-patch version-minor version-major changelog tag

# Efficiency verification configuration: use the activated project runtime.
EFFICIENCY_PYTHON ?= python
EFFICIENCY_PNPM ?= pnpm

.PHONY: check-efficiency
check-efficiency:
	cd backend && $(EFFICIENCY_PYTHON) -m pytest -m efficiency -q
	cd frontend && $(EFFICIENCY_PNPM) run check:efficiency
	cd frontend && $(EFFICIENCY_PNPM) run check:efficiency:browser

# Default target
help:
	@echo "Available commands:"
	@echo "  make check-efficiency - Verify concurrent reuse, cancellation, invalidation and live authorization"
	@echo "  make version-patch    - Bump patch version (0.1.0 -> 0.1.1)"
	@echo "  make version-minor    - Bump minor version (0.1.0 -> 0.2.0)"
	@echo "  make version-major    - Bump major version (0.1.0 -> 1.0.0)"
	@echo "  make changelog        - Generate changelog from git history"
	@echo "  make tag              - Create git tag for current version"

# Version bumping for frontend
version-patch-frontend:
	cd frontend && pnpm run version:patch

version-minor-frontend:
	cd frontend && pnpm run version:minor

version-major-frontend:
	cd frontend && pnpm run version:major

# Version bumping for backend
version-patch-backend:
	cd backend && pixi run python scripts/bump_version.py patch

version-minor-backend:
	cd backend && pixi run python scripts/bump_version.py minor

version-major-backend:
	cd backend && pixi run python scripts/bump_version.py major

# Combined version bumping (both frontend and backend)
version-patch: version-patch-frontend version-patch-backend
	@echo "Bumped patch version for both frontend and backend"

version-minor: version-minor-frontend version-minor-backend
	@echo "Bumped minor version for both frontend and backend"

version-major: version-major-frontend version-major-backend
	@echo "Bumped major version for both frontend and backend"

# Changelog generation
changelog:
	@echo "Generating changelog..."
	@echo "Please update CHANGELOG.md manually based on git history"
	@echo "Recent commits:"
	@git log --oneline -10

# Tag creation
tag:
	@echo "Creating git tag..."
	@cd backend && pixi run python scripts/bump_version.py patch --tag
	@echo "Tag created successfully"
