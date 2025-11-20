#!/bin/bash
# Script to set up the GitHub repository for Scriptorium

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "GitHub CLI (gh) is not installed."
    echo "Install it from: https://cli.github.com/"
    echo ""
    echo "Or create the repository manually at: https://github.com/new"
    echo "Repository name: scriptorium"
    exit 1
fi

# Check if already logged in
if ! gh auth status &> /dev/null; then
    echo "Please log in to GitHub CLI first:"
    echo "  gh auth login"
    exit 1
fi

# Create the repository
echo "Creating repository 'scriptorium' on GitHub..."
gh repo create scriptorium --public --description "Scriptorium - Publish books and publications to Nostr"

# Add remote if not already added
if ! git remote get-url origin &> /dev/null; then
    echo "Adding GitHub remote..."
    git remote add origin https://github.com/Silberengel/scriptorium.git
else
    echo "Updating GitHub remote..."
    git remote set-url origin https://github.com/Silberengel/scriptorium.git
fi

echo ""
echo "Repository created! Next steps:"
echo "1. git add ."
echo "2. git commit -m 'Initial commit'"
echo "3. git push -u origin main  (or master, depending on your default branch)"

