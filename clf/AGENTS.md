# Cognition Layers Documentation

## Purpose

The `clf/` directory contains the core components for the Cognition Layers plugin, which provide cognitive behavior, pattern detection, and self-correction capabilities within the Agent Zero framework.

### Ownership

- **Primary Owner**: AI Agents
- **Purpose**: Facilitate cognitive functions, pattern detection, and self-correction.

---

## Documentation Hierarchy

- **Level 1 (Core Domain Docs)**: Architecture and contracts for core components in `clf/`.

---

## Core Components

### CognitionAdapter

- **Purpose**: Adapts the plugin to Agent Zero.
- **Implementation Contracts**:
  - Builds context for agent operations.
  - Manages tool invocation and response payloads.
  - Handles context snapshots and capability summaries.

### EventBus

- **Purpose**: Manages event publishing and subscription.
- **Implementation Contracts**:
  - Publishes and subscribes to events.
  - Configures event history and queue limits.
  - Provides statistics and recent event retrieval.

### CognitionOrchestrator

- **Purpose**: Orchestrates cognitive tasks.
- **Implementation Contracts**:
  - Registers and manages components.
  - Processes and evaluates cognitive tasks.
  - Handles orchestration plans and execution.

### VerificationGuardian

- **Purpose**: Ensures tool and operation verification.
- **Implementation Contracts**:
  - Verifies tool calls and arguments.
  - Analyzes shell commands, file destinations, and content payloads.
  - Manages verification cache and policies.

### PatternDetector

- **Purpose**: Detects patterns in agent behavior.
- **Implementation Contracts**:
  - Detects and classifies patterns from observations.
  - Validates and stores detected patterns.
  - Queries and retrieves patterns.

### PatternPersistenceCore

- **Purpose**: Persists detected patterns.
- **Implementation Contracts**:
  - Saves and loads patterns.
  - Manages pattern transitions and deletions.
  - Provides pattern summaries and retrieval.

### ContextManager

- **Purpose**: Manages context and state.
- **Implementation Contracts**:
  - Creates and restores checkpoints.
  - Compacts context to manage memory usage.
  - Provides context summaries.

### SelfCorrectionTrigger

- **Purpose**: Triggers self-correction mechanisms.
- **Implementation Contracts**:
  - Evaluates failures and builds correction decisions.
  - Manages runtime state and correction summaries.

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
2. **Pattern Updates**: Update pattern detection rules and persistence mechanisms.
3. **Self-Correction**: Implement and test self-correction mechanisms.

---

## Documentation Ownership

- **Module-local `AGENTS.md`**: Owns the concrete contracts for major modules and surfaces in `clf/`.