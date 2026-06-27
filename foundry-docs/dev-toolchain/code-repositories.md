# Code Repositories

> Code Repositories is Foundry's Git-backed environment for authoring production transforms, pipelines, and Functions in Python, Java, SQL, and TypeScript — with branches, code review, and CI.

## What it is

Code Repositories is where engineers write the code that powers Foundry pipelines and logic. It's a full software-development environment inside the platform: every repository is Git-backed, supports branches and pull requests, runs automated checks (CI) on each commit, and manages language environments and dependencies for you. It's the code-first counterpart to the visual Pipeline Builder, and the home for authoring **Functions** and **Transforms**.

## When to use it

- You need version-controlled, reviewed, testable code for transforms or Functions.
- Logic is too complex/custom for Pipeline Builder.
- You want to share libraries across pipelines and teams.
- You're authoring TypeScript/Python **Functions** on the Ontology.

**When NOT to use it / alternatives:** For no-code pipelines use **Pipeline Builder**; for interactive exploration use **Code Workbook** or **Code Workspaces**.

## Key concepts & terminology

- **Repository** — A Git project containing transform/function code and config.
- **Branch** — An isolated line of development (default is usually `master`).
- **Commit / Pull Request** — Standard Git change and review workflow.
- **Checks (CI)** — Automated tests/validations run on each branch before merge.
- **Template** — A starter repo type (Python transforms, Functions, etc.).
- **Build** — Running a transform from the repo to produce dataset output.
- **Environment / dependencies** — Managed library versions (conda/maven) per repo.

## Core capabilities / features

- **Multiple languages** — Python, Java, SQL for transforms; TypeScript/Python for Functions.
- **Git workflow** — Branches, commits, pull requests, and merge controls.
- **Continuous Integration** — Tests and checks run automatically on each branch.
- **In-browser editor** — Code, preview, and build without local setup; or use Code Workspaces for a full IDE.
- **Dependency management** — Add and pin libraries with managed environments.
- **Preview & build on branch** — Test transforms against real data safely before merging.
- **Reusable libraries** — Publish shared code consumed by other repositories.

## How it works / typical workflow

1. **Create a repository** from a template (e.g., Python Transforms or Functions).
2. **Branch** off `master` to develop safely.
3. Write transform/function code; **add dependencies** as needed.
4. **Preview/build** against real datasets on the branch.
5. Add **unit tests and checks**; let CI validate.
6. Open a **pull request**, get review, and **merge**.
7. Attach **schedules** (transforms) or **publish** (Functions) to put it into production.

## Example

A Python transforms repo contains `clean_orders.py` with an `@transform_df` that filters and enriches `raw/orders` into `clean/orders`. A teammate branches, adds a unit test, opens a PR; CI runs the test; after review it merges and a schedule rebuilds the output hourly.

## How it connects to the rest of Foundry

- **Transforms** — The Transforms API is authored here.
- **Functions** — TypeScript/Python Functions on Objects live in repositories.
- **Datasets / Pipeline Builder** — Repos produce datasets just like pipelines; you can mix both.
- **Schedules / Data Lineage** — Repo builds run on schedules and appear in lineage.
- **Code Workspaces** — A richer IDE (VS Code/Jupyter) experience over similar workflows.

## Tips & gotchas for learners

- **Always branch** — never iterate directly on `master`.
- **Let CI catch mistakes** — write checks and tests early.
- **Pin dependencies** for reproducible builds.
- **Functions vs transforms** — same home, different purpose (interactive logic vs batch datasets).
- **Preview is sampled** — confirm full builds for edge cases.

## Official documentation

- [Code Repositories: Overview](https://www.palantir.com/docs/foundry/code-repositories/overview)
- [Transforms: Overview](https://www.palantir.com/docs/foundry/transforms/overview)
- [Dev toolchain: Overview](https://www.palantir.com/docs/foundry/dev-toolchain/overview)
