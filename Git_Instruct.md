# Branch workflow
main is clean and matches the remote. When you're ready to start your own work:

# Create and switch to your feature branch
git checkout -b justu/your-topic-name
# After making changes
git add .
git commit -m "Your commit message"
git push -u origin justu/your-topic-name
To update main with teammate changes later:


git checkout main
git pull origin main