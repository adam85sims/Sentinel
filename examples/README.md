# Examples

This directory contains example configs, auditor configs, and scripts
demonstrating how to use agent-frameworks.

## Config Examples

| File | Description |
|------|-------------|
| `agent-frameworks.minimal.yaml` | Just governance — pattern-memory and automation use defaults |
| `agent-frameworks.full.yaml` | All modules configured with multiple model fallbacks |
| `agent-frameworks.ollama.yaml` | Ollama-only setup — no cloud APIs needed |
| `agent-frameworks.lmstudio.yaml` | LM Studio setup (OpenAI-compatible on port 1234) |

## Auditor Config Examples

| File | Description |
|------|-------------|
| `governance/auditor.ollama.yaml` | Ollama backend (port 11434) |
| `governance/auditor.none.yaml` | No LLM — deterministic comparators only (CI/CD) |
| `governance/auditor.vllm.yaml` | vLLM backend (port 8000) |

## Script Examples

| File | Description |
|------|-------------|
| `example_audit.py` | Run a governance audit and inspect results |
| `example_model_routing.py` | Route tasks to optimal models by capability tier |
| `example_session.py` | Session state + work queue management |
| `example_pattern_memory.py` | Record and retrieve corrections (storage layer directly) |

## Running Examples

```bash
# From the project root:

# Audit example
python3 examples/example_audit.py .

# Model routing (needs agent-frameworks.yaml in root)
python3 examples/example_model_routing.py

# Session state + work queue
python3 examples/example_session.py .

# Pattern memory (needs pattern-memory on path)
python3 examples/example_pattern_memory.py
```

## Using Example Configs

To use an example config, copy it to your project root:

```bash
# Minimal setup
cp examples/agent-frameworks.minimal.yaml agent-frameworks.yaml

# Full setup
cp examples/agent-frameworks.full.yaml agent-frameworks.yaml

# Ollama-only
cp examples/agent-frameworks.ollama.yaml agent-frameworks.yaml

# Copy auditor config to governance/
cp examples/governance/auditor.ollama.yaml governance/auditor.yaml
```

Or just run `agent-fw-setup init` which generates a config for you based
on what's detected in your environment.