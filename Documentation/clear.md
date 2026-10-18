I created a new GitHub repository because my previous Git repository was nested inside the `Thesis` folder, causing other folders outside it to be excluded from Git tracking.

I want to centralize my entire project into ONE Git repository.

Please:

1. Inspect the complete project directory structure and identify the top-level folder.
2. Identify all existing `.git` directories, including the nested repository inside `Thesis`.
3. Confirm which directory is currently the root of the new repository.
4. Make sure all project folders are managed by the new top-level repository.
5. Preserve the old repository's Git history in a safe backup before making changes.
6. Do not delete or overwrite any source code, datasets, trained models, or project documentation.
7. Prepare a root `.gitignore` that excludes temporary files, caches, virtual environments, secrets, and unnecessary generated dependencies.
8. Check for large files that may exceed GitHub's limits. Do not automatically remove datasets or model weights.
9. Verify that Git detects all intended project files, including those previously excluded because they were outside the old repository.
10. Explain the changes and show the final repository structure.

**Safety requirements:**
- Do not delete existing `.git` metadata until it has been safely backed up.
- Do not use force push.
- Do not rewrite existing Git history.
- Do not commit or push anything until the repository structure has been verified.
- If the old repository is configured as a submodule, identify that before making changes.

**Goal:** One clean, centralized GitHub repository that tracks the complete Thesis project, without losing any existing project files or important Git history.