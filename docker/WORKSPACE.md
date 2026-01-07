# AI Workspace System

Persistent, isolated development environment for AI to build and test code.

## Quick Start

Start workspace: docker-compose up -d workspace
Test it: python examples/workspace_example.py

## What It Provides

- Full Ubuntu environment
- Python 3.11 + common packages
- Git, Node.js, build tools
- Persistent storage
- Safe isolation from host

## Workspace Structure

/workspace/
  projects/     - Long-term projects
  experiments/  - Quick tests
  data/         - Datasets
  tools/        - Utility scripts
  tmp/          - Temporary files
  output/       - Results

## Safety Features

- Execution timeout (5 min)
- Output size limits (1MB)
- Resource limits (2 CPU, 2GB RAM)
- Contained filesystem

## Troubleshooting

Container won't start:
  docker-compose logs workspace

Reset workspace:
  docker-compose down -v
  docker-compose up -d workspace
