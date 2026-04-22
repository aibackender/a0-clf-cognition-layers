# Extensions Documentation

## Purpose
The `extensions/` directory contains hooks and WebUI extensions for various stages of the Agent Zero lifecycle.

### Ownership

- **Primary Owner**: AI Agents
- **Purpose**: Provide hooks for various stages of the Agent Zero lifecycle and WebUI interactions.

---

## Documentation Hierarchy

- **Level 1 (Core Domain Docs)**: Architecture and contracts for extensions in `extensions/`.

---

## Extensions Overview

### Python Hooks

- **Purpose**: Handle various stages of the Agent Zero lifecycle.
- **Implementation Contracts**:
  - **Agent Initialization**: Initializes the cognition layers runtime.
  - **Pre-LLM Call**: Preflight checks before LLM calls.
  - **Tool Execution Before/After**: Handles tool execution stages.
  - **Message Loop Prompts After**: Injects prompts after message loop prompts.
  - **Message Loop End**: Handles end of message loop.

### WebUI Extensions

- **Purpose**: Provide user interface interactions.
- **Implementation Contracts**:
  - **Runtime Handler**: Manages runtime interactions in the WebUI.

---

## Implementation Rules

### Code Quality

- Maintain high code quality standards.
- Follow consistent coding practices and style guides.

### Documentation

- Ensure all code and configurations are well-documented.
- Update documentation in the same session as code changes.

### Security

- Follow security best practices to protect data and operations.

---

## Workflows

### Development Workflow

1. **Code Review**: All changes should be reviewed by the AI agents.
2. **Testing**: Ensure all components are tested for functionality and robustness.
3. **Documentation**: Update documentation as needed.

### Maintenance Workflow

1. **Monitoring**: Continuously monitor system performance and logs.
2. **Pattern Updates**: Update hooks and UI interactions as needed.

---

## Documentation Ownership

- **Module-local `AGENTS.md`**: Owns the concrete contracts for major modules and surfaces in `extensions/`.
