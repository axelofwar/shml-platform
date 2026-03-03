# SHML CLI

Clean command-line interface for the SHML Platform.

## Installation

```bash
# One-line setup
./cli/setup.sh

# Or manually:
pip install typer rich httpx
chmod +x cli/shml.py
ln -sf $(pwd)/cli/shml.py ~/.local/bin/shml
```

## Quick Start

```bash
# Show all commands
shml --help

# Quick agent task
shml run "Create a REST API endpoint for user authentication"

# Quick chat
shml chat "Explain async/await in Python"

# Check status
shml status

# GPU status
shml gpu status
```

## Commands

### Agent Commands (`shml agent`)

```bash
# Run full ACE workflow (Generator-Reflector-Curator)
shml agent run "Create a health check endpoint"
shml agent run "Fix the bug in auth.py" --category debugging
shml agent run "Add tests for user service" --stream

# Quick chat (no ACE workflow)
shml agent chat "How do I optimize this SQL query?"
shml agent chat "Explain this error message" -m nemotron

# Check agent service status
shml agent status
```

### GPU Commands (`shml gpu`)

```bash
# Show GPU status with memory/utilization
shml gpu status

# Yield GPU for training (unloads inference model)
shml gpu yield --gpu 0 --job my-training

# Reclaim GPU after training (reloads inference model)
shml gpu reclaim --gpu 0 --job my-training
```

### Training Commands (`shml training`)

```bash
# Check active training jobs
shml training status

# Submit training (auto-yields GPU)
shml training submit scripts/train.py --gpu 0
```

### MCP Commands (`shml mcp`)

```bash
# List available MCP tools
shml mcp tools

# Call MCP tools directly
shml mcp call gpu_status
shml mcp call training_status
shml mcp call mlflow_query -a '{"query_type": "experiments"}'
shml mcp call vision_analyze -a '{"image_path": "/path/to/image.jpg", "prompt": "Describe this image"}'
```

### Platform Commands (`shml platform`)

```bash
# Show platform status
shml platform status

# Start/stop/restart services
shml platform start inference
shml platform stop mlflow
shml platform restart ray

# View service logs
shml platform logs agent-service -f
shml platform logs nemotron-api --lines 100
```

## Shell Aliases

For even shorter commands, source the aliases file:

```bash
# Add to ~/.bashrc or ~/.zshrc
source /path/to/shml-platform/cli/aliases.sh
```

Then use:

```bash
# Core shortcuts
sa       # shml agent
sas      # shml agent status
sar      # shml agent run

# GPU shortcuts
sg       # shml gpu
sgs      # shml gpu status

# Training shortcuts
st       # shml training
sts      # shml training status

# Platform shortcuts
sp       # shml platform
sps      # shml platform status
pstart   # ./start_all_safe.sh start
pstop    # ./start_all_safe.sh stop

# Functions
agentrun "Create an API"  # Run agent task
agentchat "Question?"     # Quick chat
healthcheck               # Check all services
```

## Tab Completion

Tab completion is installed automatically:

```bash
shml a<TAB>        # completes to 'agent'
shml agent r<TAB>  # completes to 'run'
```

To reinstall completion:

```bash
shml --install-completion bash
shml --install-completion zsh
```

## Environment Variables

Configure the CLI with environment variables:

```bash
export SHML_AGENT_URL="http://localhost/api/agent"
export SHML_NEMOTRON_URL="http://localhost:8010"
export SHML_DIR="/path/to/shml-platform"
```

## Examples

### Full Agentic Development Workflow

```bash
# 1. Check platform is ready
shml status

# 2. Run complex coding task
shml agent run "Implement a WebSocket server with authentication,
rate limiting, and connection pooling. Create the following files:
- websocket/server.py
- websocket/auth.py
- websocket/rate_limiter.py
- tests/test_websocket.py"

# 3. Monitor GPU during execution
shml gpu status

# 4. Check training status if model training involved
shml training status
```

### Training Workflow with GPU Management

```bash
# 1. Check current GPU status
shml gpu status

# 2. Yield GPU for training (unloads Nemotron)
shml gpu yield --gpu 0 --job face-detection-v2

# 3. Run training script
python ray_compute/jobs/face_detection_training.py

# 4. Reclaim GPU when done (reloads Nemotron)
shml gpu reclaim --gpu 0 --job face-detection-v2
```

### Quick Debugging Session

```bash
# Ask about an error
shml chat "I'm getting 'CUDA out of memory' errors. How do I debug this?"

# Check GPU memory
shml gpu status

# View service logs
shml platform logs agent-service --lines 50
```
