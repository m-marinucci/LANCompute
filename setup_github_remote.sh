#!/bin/bash

# Script to set up GitHub remote for LANCompute

echo "=== GitHub Remote Setup for LANCompute ==="
echo ""
echo "Before running this script, please:"
echo "1. Go to https://github.com/new"
echo "2. Create a new repository named 'LANCompute'"
echo "3. Make it public or private as you prefer"
echo "4. DO NOT initialize with README, .gitignore, or license"
echo ""
read -p "Have you created the repository? (y/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Please create the repository first, then run this script again."
    exit 1
fi

echo ""
read -p "Enter your GitHub username: " username
echo ""

# Set up remote
remote_url="https://github.com/${username}/LANCompute.git"
echo "Adding remote: $remote_url"
git remote add origin "$remote_url"

echo ""
echo "Remote added successfully!"
echo ""
echo "To push your code, run:"
echo "  git push -u origin main"
echo ""
echo "If you use SSH keys with GitHub, you can change the remote URL to SSH:"
echo "  git remote set-url origin git@github.com:${username}/LANCompute.git"